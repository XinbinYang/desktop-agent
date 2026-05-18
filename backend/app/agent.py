import json
import logging
import ntpath
import os
import re
import time
import uuid
import copy
from collections import OrderedDict
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.config import load_config, get_provider_for_model, get_model_for_agent, get_thinking_intensity_for_agent
from app.coding_context import build_repo_map, format_repo_map_summary
from app.coding_runs import (
    complete_run,
    create_coding_run,
    record_event,
    reset_run_context,
    set_run_context,
)
from app.collaboration.executor import result_from_execute_events, run_consult_worker, run_execute_agent_events
from app.collaboration.manager import (
    add_task as collab_add_task,
    complete_run as collab_complete_run,
    create_run as collab_create_run,
    list_events as collab_list_events,
    record_event as collab_record_event,
    update_task as collab_update_task,
)
from app.collaboration.models import ResultPacket, TaskPacket
from app.collaboration.parser import CodingMention, classify_coding_intent, parse_coding_mention
from app.models import ModelRouter
from app.memory import build_memory_prompt
from app.project_manager import ProjectManager
from app.project_rules import build_rules_prompt
from app.roles import RoleManager  # deprecated — kept for backward compat
from app.agents.manager import AgentManager
from app.runtime_paths import runtime_dir, runtime_file, backend_root
from app.skills import SkillManager
from app.tools import build_tools_description, get_tool, get_tool_schemas, list_tool_names, DynamicToolRegistry
from app.tools.browser_tool import set_browser_session
from app.tools.desktop_tool import ScreenshotTool
from app.tools.worker_tool import cancel_workers_for_session
from app.tools.workflow_tool import get_recorder
from app.message_utils import trim_messages, parse_tool_args, execute_tool, resolve_mentions
from app.workflow.models import PlanState, PlanTodo, PlanQuestion, PlanQuestionOption, PlanDraft, PlanStep
from app.workflow.plan_files import write_plan_file, read_plan_file

logger = logging.getLogger(__name__)

SESSIONS_DIR = runtime_dir("sessions")
SESSION_REGISTRY_PATH = runtime_file("session_registry.json")
GLOBAL_PROJECT_KEY = "__global__"

# Internal: resume agent loop after user clicks Build (WebSocket `build_plan`).
PLAN_CONTINUE_MARKER = "__plan_continue__"

_LOCAL_MESSAGE_META_KEYS: frozenset[str] = frozenset({
    "message_id",
    "turn_id",
    "created_at",
    "checkpoint_id",
})

_LLM_MESSAGE_KEYS: frozenset[str] = frozenset({
    "role",
    "content",
    "name",
    "tool_call_id",
    "tool_calls",
    "reasoning_content",
})

# Plan-mode planning phase: only these tools may be offered / executed until approved.
READONLY_PLAN_TOOLS: frozenset[str] = frozenset({
    "file_read",
    "file_list",
    "file_search",
    "knowledge_search",
    "knowledge_list",
    "git_status",
    "git_diff",
    "screenshot",
    "browser_screenshot",
    "get_screen_size",
})

_BLOCKING_REVIEW_SEVERITIES: frozenset[str] = frozenset({"blocker", "critical", "error", "important"})
_VERIFICATION_COMMAND_HINTS: tuple[str, ...] = (
    "pytest",
    "vitest",
    "npm test",
    "npm run test",
    "npm run build",
    "npm run lint",
    "pnpm test",
    "pnpm build",
    "pnpm lint",
    "yarn test",
    "yarn build",
    "yarn lint",
    "tsc",
    "mypy",
    "ruff",
    "eslint",
    "cargo test",
    "cargo check",
    "go test",
    "dotnet test",
    "gradle test",
    "mvn test",
)


def _normalize_project_key(project_path: str | None = None) -> str:
    if not project_path:
        try:
            project = ProjectManager.get_current()
            if project:
                project_path = project.get("path")
        except Exception:
            project_path = None
    if not project_path:
        return GLOBAL_PROJECT_KEY
    return str(project_path).replace("\\", "/").rstrip("/").lower()


def _load_session_registry() -> Dict[str, Any]:
    if not SESSION_REGISTRY_PATH.exists():
        return {"personal": {}, "coding": {"last_session_by_project": {}}}
    try:
        data = json.loads(SESSION_REGISTRY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    personal = data.setdefault("personal", {})
    if not isinstance(personal, dict):
        data["personal"] = {}
    coding = data.setdefault("coding", {})
    if not isinstance(coding, dict):
        coding = {}
        data["coding"] = coding
    if not isinstance(coding.get("last_session_by_project"), dict):
        coding["last_session_by_project"] = {}
    return data


def _save_session_registry(data: Dict[str, Any]) -> None:
    try:
        tmp = SESSION_REGISTRY_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SESSION_REGISTRY_PATH)
    except OSError:
        pass


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif block.get("type") == "image_url":
                    parts.append("[image]")
                elif block.get("type") == "tool_result":
                    parts.append(str(block.get("content") or ""))
                else:
                    parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)


def _estimate_tokens(text: Any) -> int:
    """Cheap cross-provider estimate used only for UI context health."""
    body = _text_from_content(text)
    if not body:
        return 0
    # Mixed Chinese/English/code tends to land around 3-4 chars/token.
    return max(1, int(len(body) / 3.6))


def _usage_input_tokens(usage: Dict[str, Any] | None) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in ("prompt_tokens", "input_tokens", "total_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value > 0:
            return value
    total = 0
    for key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            total += value
    fresh = usage.get("input_tokens")
    if isinstance(fresh, int):
        total += fresh
    return total


def _usage_output_tokens(usage: Dict[str, Any] | None) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in ("completion_tokens", "output_tokens", "total_output_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return 0


def _load_session_data(session_id: str) -> Optional[Dict[str, Any]]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _session_title_from_data(data: Dict[str, Any]) -> str:
    title = str(data.get("title") or "").strip()
    if title:
        return title[:80]
    for msg in data.get("messages", []):
        if msg.get("role") == "user" and isinstance(msg.get("content"), str) and msg["content"].strip():
            return msg["content"].strip()[:80]
    plan_state = data.get("plan_state")
    if isinstance(plan_state, dict) and isinstance(plan_state.get("goal"), str):
        return plan_state["goal"].strip()[:80]
    return ""


def _session_title_from_messages(messages: List[Dict[str, Any]], plan_state: PlanState) -> str:
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), str) and msg["content"].strip():
            return msg["content"].strip()[:80]
    if plan_state.goal:
        return plan_state.goal[:80]
    return ""


def _session_has_history_data(data: Dict[str, Any]) -> bool:
    return any(msg.get("role") != "system" for msg in data.get("messages", []))


def _session_has_history(session: "AgentSession") -> bool:
    return any(msg.get("role") != "system" for msg in session.messages)


def _resolve_stored_agent_type(data: Dict[str, Any]) -> str:
    raw = data.get("agent_type")
    if raw in ("personal", "coding"):
        return raw
    return AgentManager.get_agent_type_for_role(data.get("role_id", "desktop-agent"))


def _session_record_matches(
    session_id: str,
    *,
    agent_type: str,
    project_path: str | None = None,
) -> bool:
    live = _sessions.get(session_id)
    if live and live.agent_type == agent_type:
        return True if not project_path else _normalize_project_key(project_path) == _normalize_project_key(None)

    data = _load_session_data(session_id)
    if not data or _resolve_stored_agent_type(data) != agent_type:
        return False
    if project_path:
        stored = data.get("project_path")
        if _normalize_project_key(stored) != _normalize_project_key(project_path):
            return False
    return True


def list_session_records(project_path: str = "", agent_type: str = "") -> List[Dict[str, Any]]:
    registry = _load_session_registry()
    primary_id = registry.get("personal", {}).get("primary_session_id")
    sessions: List[Dict[str, Any]] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored_agent_type = _resolve_stored_agent_type(data)
            if agent_type and stored_agent_type != agent_type:
                continue
            sp = data.get("project_path")
            if project_path and _normalize_project_key(sp) != _normalize_project_key(project_path):
                continue
            session_id = data.get("session_id", path.stem)
            is_primary = stored_agent_type == "personal" and session_id == primary_id
            sessions.append({
                "id": session_id,
                "title": _session_title_from_data(data),
                "project_path": sp,
                "model_id": data.get("model_id", ""),
                "role_id": data.get("role_id", AgentManager.get_default_role(stored_agent_type)),
                "agent_type": stored_agent_type,
                "message_count": len(data.get("messages", [])),
                "updated_at": path.stat().st_mtime,
                "is_primary": is_primary,
            })
        except Exception:
            pass
    return sorted(
        sessions,
        key=lambda s: (0 if s.get("is_primary") else 1, -float(s.get("updated_at", 0))),
    )


def _shell_command_looks_like_verification(command: str) -> bool:
    lowered = (command or "").lower()
    return any(hint in lowered for hint in _VERIFICATION_COMMAND_HINTS)


def _review_passed(review: Optional[Dict[str, Any]]) -> Optional[bool]:
    if review is None:
        return None
    blocking = review.get("blocking_findings")
    if isinstance(blocking, list):
        return len(blocking) == 0
    findings = review.get("findings") or []
    return not any(
        str(finding.get("severity", "")).lower() in _BLOCKING_REVIEW_SEVERITIES
        for finding in findings
        if isinstance(finding, dict)
    )


def _completion_quality_payload(
    *,
    files_modified: bool,
    latest_verification: Optional[Dict[str, Any]],
    latest_review: Optional[Dict[str, Any]],
    unstructured_verification_seen: bool,
) -> Dict[str, Any]:
    if latest_verification:
        verification_passed: Optional[bool] = bool(latest_verification.get("passed"))
        verification_source = "verify_project"
    elif files_modified and unstructured_verification_seen:
        verification_passed = None
        verification_source = "shell_execute"
    elif files_modified:
        verification_passed = False
        verification_source = "missing"
    else:
        verification_passed = None
        verification_source = "not_required"

    if latest_review:
        review_passed = _review_passed(latest_review)
        blocking_findings = latest_review.get("blocking_findings")
        blocking_count = len(blocking_findings) if isinstance(blocking_findings, list) else None
    elif files_modified:
        review_passed = False
        blocking_count = None
    else:
        review_passed = None
        blocking_count = None

    return {
        "verification_passed": verification_passed,
        "verification_source": verification_source,
        "verification_command": latest_verification.get("command") if latest_verification else None,
        "green_level": latest_verification.get("green_level") if latest_verification else None,
        "review_passed": review_passed,
        "review_blocking_findings": blocking_count,
    }


class AgentSession:
    MAX_HISTORY_MESSAGES = 20

    def __init__(self, model_id: str, session_id: str = "default", role_id: str = "desktop-agent", agent_type: str | None = None):
        self.session_id = session_id
        # agent_type is the new primary field; role_id kept for backward compat
        self._agent_type = agent_type or AgentManager.get_agent_type_for_role(role_id)
        self._role_id = (
            role_id
            if AgentManager.get_agent_type_for_role(role_id) == self._agent_type
            else AgentManager.get_default_role(self._agent_type)
        )

        # Per-agent model and thinking intensity tracking (config defaults)
        self._agent_models: Dict[str, str] = {}
        self._agent_thinking: Dict[str, str] = {}
        for at in ("personal", "coding"):
            self._agent_models[at] = get_model_for_agent(at)
            self._agent_thinking[at] = get_thinking_intensity_for_agent(at)

        # Use the explicitly-provided model_id; per-agent config defaults are
        # applied only on explicit switch_agent() calls, not here.
        self.model_id = model_id
        self.router = ModelRouter(self.model_id)
        self.messages: List[Dict[str, Any]] = []
        self.iteration = 0
        self.max_iterations = load_config().settings.max_iterations
        self.screenshot_on_step = load_config().settings.screenshot_on_step
        self._cancelled = False
        self._active_workers: List[Any] = []
        self._last_user_message = ""
        self._rag_cache_key: str = ""
        self._rag_cache_text: str = ""
        self._rag_cache_sources: List[Dict[str, Any]] = []
        self._rag_context_sources: List[Dict[str, Any]] = []
        self.dynamic_registry = DynamicToolRegistry()
        self.chat_mode = "agent"
        self.thinking_intensity = self._agent_thinking.get(self._agent_type, "medium")
        self.plan_state = PlanState()
        self._plan_exec_hint_sent = False
        self._repo_map_cache: Optional[Dict[str, Any]] = None
        self.compaction_summary: str = ""
        self._last_usage: Dict[str, Any] = {}
        self._last_context_usage: Dict[str, Any] = {}
        self.team_id: str | None = None
        self.team_name: str = ""
        self._setup_system_prompt()

    @property
    def agent_type(self) -> str:
        return self._agent_type

    @agent_type.setter
    def agent_type(self, value: str) -> None:
        self._agent_type = value
        self._role_id = AgentManager.get_default_role(value)

    @property
    def role_id(self) -> str:
        """Backward-compatible alias for _role_id."""
        return self._role_id

    @role_id.setter
    def role_id(self, value: str) -> None:
        self._role_id = value
        # If the role maps to a different agent_type, update it
        mapped = AgentManager.get_agent_type_for_role(value)
        if mapped != self._agent_type:
            self._agent_type = mapped

    def _resolve_agent_model(self) -> str:
        """Get the effective model ID for the current agent type from config."""
        return get_model_for_agent(self._agent_type)

    def _build_system_prompt(self) -> str:
        tools_desc = build_tools_description(self.dynamic_registry, agent_type=self._agent_type)
        system_msg = AgentManager.render_prompt(self._agent_type, tools_desc, self._last_user_message)

        model_name = self.model_id
        try:
            provider_info = get_provider_for_model(self.model_id)
            if provider_info:
                _pn, _pc = provider_info
                for m in _pc.models:
                    if m.id == self.model_id:
                        model_name = m.name
                        break
        except Exception:
            pass
        system_msg = f"You are powered by the model {model_name}.\n\n" + system_msg

        project = ProjectManager.get_current()
        if project:
            project_ctx = "\n\n## Current Project\n"
            project_ctx += f"- Name: {project['name']}\n"
            project_ctx += f"- Path: {project['path']}\n"
            if project.get("git_branch"):
                project_ctx += f"- Git branch: {project['git_branch']}\n"
            if project.get("git_remote"):
                project_ctx += f"- Git remote: {project['git_remote']}\n"
            system_msg += project_ctx

            # Inject project-level and user-level agent rules (.desktop-agent.md / AGENTS.md)
            branch = project.get("git_branch", "") if project else ""
            rules_text = build_rules_prompt(project["path"], branch)
            if rules_text:
                system_msg += rules_text

            # Inject cross-session memory
            memory_text = build_memory_prompt(project["path"])
            if memory_text:
                system_msg += "\n\n" + memory_text

            # Coding Agent: inject repo map and operating rules
            if self._agent_type == "coding":
                try:
                    coding_cfg = load_config().coding_agent
                    if coding_cfg.enabled and coding_cfg.auto_generate_repo_map:
                        if self._repo_map_cache is None:
                            self._repo_map_cache = build_repo_map(project["path"])
                        repo_map = self._repo_map_cache
                        system_msg += "\n\n## Coding Agent Context\n"
                        system_msg += format_repo_map_summary(repo_map, max_chars=4500)
                        system_msg += (
                            "\n\n## Coding Agent Operating Rules\n"
                            "- USER IS NON-PROGRAMMER: Treat the user's words as product intent, not an implementation spec. "
                            "Make technical decisions yourself using existing project patterns. Ask only about user-visible behavior "
                            "or destructive/security-sensitive choices.\n"
                            "- PARALLEL EXPLORE FIRST: For any task touching 3+ files or an unfamiliar codebase, "
                            "use `dispatch_parallel` to launch multiple `explorer` workers simultaneously — one per "
                            "subsystem (e.g., API layer, core logic, frontend, tests). Each explorer reads its area "
                            "and reports back. Synthesize their reports before dispatching an architect. "
                            "Never read files one-by-one inline when you could parallelize exploration.\n"
                            "- SCALE TO TASK: Known 1-2 file fix → inline edits. Unknown scope / 3+ files → "
                            "parallel explore → architect → editor(s). New feature / cross-module → full pipeline.\n"
                            "- TASK PACKET: Before non-trivial work, make the objective, scope, allowed files/resources, "
                            "acceptance criteria, verification plan, recovery policy, and reporting target explicit. "
                            "If any field is unclear, infer conservatively or ask.\n"
                            "- GREEN CONTRACT: Treat completion as evidence, not prose. `verify_project` produces the "
                            "current green level (`targeted_tests`, `workspace`, `lint`, `typecheck`, or `build`); "
                            "do not merge/apply/close out broad changes on stale or partial evidence.\n"
                            "- EVIDENCE LEDGER: In final status, distinguish observed facts from assumptions. Include "
                            "commands actually run, their exit result, known skipped checks, and unresolved blockers.\n"
                            "- AUTONOMOUS CLOSEOUT: Complete the engineering loop yourself: implement, verify, review, fix failures, "
                            "and re-run verification. Do not ask the user to choose test commands, files, branch strategy, or code structure.\n"
                            "- VERIFY ALWAYS: After any file edit, run `verify_project` (tests + typecheck). Never claim completion without showing verification output.\n"
                            "- REVIEW LAST: Call `run_review` before handing control back to user. Surface any blocking findings.\n"
                            "- CHAIN CONTEXT: Pass architect/explorer output to editor via `prior_context` parameter in `dispatch_worker`.\n"
                            "- For existing code edits, prefer `file_patch` with exact `old_text`; use `file_write` for new files or full replacement only.\n"
                            "- When tests fail, fix the implementation first. Do not edit tests to make failures pass unless the user explicitly asks.\n"
                            "- Windows: avoid Unix-only helpers (tail, head, grep, sed, awk); use PowerShell or `rg`.\n"
                            "- Use project-relative paths. In worktree mode, tools operate inside the worktree.\n"
                            "- Worker roles: explorer=parallel read-only area scan, architect=read-only plan, editor=minimal edits+verify, verifier=run tests+report, reviewer=diff review.\n"
                        )
                except Exception as e:
                    logger.warning("Coding repo map injection failed: %s", e)

            # Personal Agent: update PROJECT.md for Coding Agent reference
            if self._agent_type == "personal":
                try:
                    AgentManager.update_project_context(project)
                except Exception as e:
                    logger.warning("Project context update failed: %s", e)

        if self.chat_mode == "plan" and not self.plan_state.approved:
            try:
                plan_spec_path = backend_root() / "prompts" / "plan_mode.md"
                if plan_spec_path.exists():
                    plan_spec = plan_spec_path.read_text(encoding="utf-8")
                    system_msg += f"\n\n{plan_spec}"
            except Exception as e:
                logger.warning("Failed to inject plan_mode.md: %s", e)

        if self._last_user_message:
            matched_skills = SkillManager.match_skills(
                self._last_user_message, self.role_id, project is not None, agent_type=self._agent_type
            )
            if matched_skills:
                skill_prompt = SkillManager.build_skill_prompt(matched_skills)
                if skill_prompt:
                    system_msg += f"\n\n## Active Skills\n{skill_prompt}\n"

        # Auto-inject RAG context if knowledge base has indexed documents.
        # Cache results per (user_message, doc_count) to avoid redundant embedding
        # searches across _refresh_system_prompt calls (retry, MCP refresh, etc.).
        self._rag_context_sources = []
        _RAG_SKIP_PATTERNS = [
            r"^(你好|hi|hello|hey)[\s!！。.]*$",
            r"^(截图|screenshot|screen)[\s!！。.]*$",
            r"^(打开|open|浏览|browse)\s",
            r"^(点击|click|输入|type|按下|press)\s",
            r"^(现在几点|what time|当前时间)[\s!！。.。]*$",
            r"^(谢谢|thanks|thank you|好的|ok|okay|明白了|知道了)[\s!！。.]*$",
            r"^(运行|run|执行|execute)\s",
            r"^(新建|创建|create|new)\s+(session|会话)",
            r"^(切换|switch|change)\s+(role|角色|model|模型)",
        ]
        try:
            from app.rag.engine import get_rag_engine
            import re
            should_skip = any(
                re.match(p, self._last_user_message.strip(), re.IGNORECASE)
                for p in _RAG_SKIP_PATTERNS
            )
            if not should_skip:
                rag = get_rag_engine()
                docs = rag.list_docs()
                if docs and self._last_user_message:
                    # Build a cache key from the user message + index signature.
                    # This keeps repeated prompt refreshes cheap while still
                    # invalidating when a document is reindexed.
                    chunk_total = sum(int(d.get("chunk_count") or 0) for d in docs)
                    last_indexed = max(int(d.get("last_indexed") or 0) for d in docs)
                    doc_key = f"{self._last_user_message}::{len(docs)}::{chunk_total}::{last_indexed}"
                    if doc_key != self._rag_cache_key:
                        results = rag.search(self._last_user_message, top_k=3)
                        relevant = [r for r in results if r.score >= 0.3]
                        if relevant:
                            rag_ctx = "\n\n## Relevant Knowledge Base Context\n"
                            sources: List[Dict[str, Any]] = []
                            for r in relevant:
                                rag_ctx += f"\n### {r.source_path} (score: {r.score:.2f})\n{r.content[:800]}\n"
                                sources.append({
                                    "source_path": r.source_path,
                                    "score": r.score,
                                    "preview": r.content[:240],
                                })
                            self._rag_cache_text = rag_ctx
                            self._rag_cache_sources = sources
                        else:
                            self._rag_cache_text = ""
                            self._rag_cache_sources = []
                        self._rag_cache_key = doc_key
                    if self._rag_cache_text:
                        system_msg += self._rag_cache_text
                        self._rag_context_sources = list(self._rag_cache_sources)
        except Exception as e:
            logger.warning("RAG auto-retrieval failed: %s", e)

        # Inject team shared context
        if self.team_id:
            from .teams import build_team_context_prompt
            team_ctx = build_team_context_prompt(self.team_id, self.team_name or "Team")
            if team_ctx:
                system_msg += team_ctx

        if self.compaction_summary:
            system_msg += (
                "\n\n## Conversation Summary\n"
                "The earlier part of this session was compacted. Preserve these decisions, "
                "constraints, and open tasks while continuing from the recent messages.\n"
                f"{self.compaction_summary[:5000]}"
            )

        return system_msg

    def set_team(self, team_id: str | None, team_name: str = ""):
        """Set or clear the team for this session. Refreshes system prompt and tools."""
        from app.tools.team_context_tool import create_team_context_tool

        was_in_team = bool(self.team_id)
        self.team_id = team_id
        self.team_name = team_name

        # Register or remove team_context tool
        if team_id:
            tool = create_team_context_tool(team_id, team_name)
            self.dynamic_registry.register(tool)
        elif was_in_team:
            self.dynamic_registry.unregister("team_context")

        self._refresh_system_prompt()

    def _setup_system_prompt(self):
        self.messages.append({"role": "system", "content": self._build_system_prompt()})

    def _refresh_system_prompt(self):
        system_msg = {"role": "system", "content": self._build_system_prompt()}
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = system_msg
        else:
            self.messages.insert(0, system_msg)

    def _event(self, event_type: str, data: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
        event_data = dict(data or {})
        if run_id:
            event_data.setdefault("run_id", run_id)
        event_data.setdefault("iteration", self.iteration)
        event_data.setdefault("timestamp", time.time())
        return {"type": event_type, "data": event_data}

    def _collaboration_event(self, event: Any) -> Dict[str, Any]:
        """Convert a stored CollaborationEvent into the WebSocket event shape."""
        data = dict(getattr(event, "data", {}) or {})
        collab_run_id = getattr(event, "run_id", "")
        task_id = getattr(event, "task_id", "") or ""
        data.setdefault("run_id", collab_run_id)
        data.setdefault("collaboration_run_id", collab_run_id)
        if task_id:
            data.setdefault("task_id", task_id)
            data.setdefault("collaboration_task_id", task_id)
        data.setdefault("timestamp", getattr(event, "timestamp", time.time()))
        return self._event(getattr(event, "type", "collaboration_task_update"), data)

    def _collaboration_packet(
        self,
        mention: CodingMention,
        *,
        original_input: str,
        resolved_input: str,
        image_base64: Optional[str] = None,
    ) -> TaskPacket:
        project = ProjectManager.get_current()
        project_path = str(project.get("path") or "") if project else ""
        task = mention.task.strip() or "Open or create a Coding Agent session."
        mode = "execute" if mention.mode == "execute" else "consult"
        context: Dict[str, Any] = {
            "requested_via": mention.raw,
            "original_message": original_input,
            "project_path": project_path,
            "personal_ownership": "Personal Agent owns the final user-facing answer.",
        }
        if resolved_input and resolved_input != original_input:
            context["resolved_context"] = resolved_input[:8000]
        if image_base64:
            context["image_attached"] = True

        if mode == "consult":
            return TaskPacket(
                goal=task,
                mode="consult",
                user_intent=task,
                context=context,
                constraints=[
                    "Read-only consultation. Do not edit files or run destructive commands.",
                    "Focus on diagnosis, options, and the safest next engineering step.",
                ],
                acceptance_criteria=[
                    "Provide concise technical findings.",
                    "State whether code changes are needed.",
                    "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
                ],
                allowed_tools=[
                    "repo_map",
                    "code_search",
                    "file_outline",
                    "file_read",
                    "file_list",
                    "file_search",
                    "git_status",
                    "git_diff",
                ],
            )

        return TaskPacket(
            goal=task,
            mode="execute",
            user_intent=task,
            context=context,
            constraints=[
                "Keep changes scoped to the requested engineering task.",
                "Preserve existing user changes and do not revert unrelated work.",
                "Report blockers instead of guessing through destructive or private decisions.",
            ],
            acceptance_criteria=[
                "Implementation satisfies the user goal.",
                "Verification evidence is reported.",
                "Review findings or residual blockers are reported.",
                "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
            ],
        )

    async def _handle_coding_mention(
        self,
        mention: CodingMention,
        *,
        original_input: str,
        resolved_input: str,
        image_base64: Optional[str],
        outer_run_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Handle explicit `@coding agent` delegation before the Personal LLM turn."""
        active_turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        active_checkpoint_id = f"chk_{uuid.uuid4().hex[:12]}"
        user_msg = (
            self.router.build_vision_message(original_input, image_base64)
            if image_base64
            else {"role": "user", "content": original_input}
        )
        user_msg["source"] = "user"
        self._stamp_message(user_msg, turn_id=active_turn_id, checkpoint_id=active_checkpoint_id)
        self.messages.append(user_msg)
        self._trim_messages()
        yield self._event("context_usage", self.context_usage(), outer_run_id)

        if mention.mode == "handoff":
            text = (
                "我已经识别到你想直接进入 Coding Agent。这个会话里 Personal 仍保持主入口，"
                "我会把后续明确的代码任务通过 `@coding agent ...` 委托给 Coding；"
                "如果要完整切到 Coding Agent，请使用界面的 Agent 切换。"
            )
            assistant_msg = {"role": "assistant", "content": text}
            self._stamp_message(assistant_msg, turn_id=active_turn_id, checkpoint_id=active_checkpoint_id)
            self.messages.append(assistant_msg)
            yield self._event(
                "suggest_agent_switch",
                {
                    "from": "personal",
                    "to": "coding",
                    "reason": "User explicitly requested @coding agent without a task.",
                },
                outer_run_id,
            )
            yield self._event("content", {"text": text}, outer_run_id)
            yield self._event("status", {"status": "completed"}, outer_run_id)
            yield self._event("run_completed", {
                "status": "completed",
                "summary": "Coding Agent handoff suggested.",
                "verification_passed": None,
                "review_passed": None,
            }, outer_run_id)
            self._save()
            return

        project = ProjectManager.get_current()
        project_path = str(project.get("path") or "") if project else ""
        packet = self._collaboration_packet(
            mention,
            original_input=original_input,
            resolved_input=resolved_input,
            image_base64=image_base64,
        )
        collab_run = collab_create_run(
            session_id=self.session_id,
            goal=packet.goal,
            mode=packet.mode,
            project_path=project_path,
            source_agent="personal",
            target_agent="coding",
        )
        task = collab_add_task(collab_run.run_id, packet)
        emitted = 0

        def new_collab_events() -> List[Dict[str, Any]]:
            nonlocal emitted
            events = collab_list_events(collab_run.run_id)
            new_events = events[emitted:]
            emitted = len(events)
            return [self._collaboration_event(event) for event in new_events]

        for event in new_collab_events():
            yield event

        collab_update_task(task.task_id, status="running")
        for event in new_collab_events():
            yield event

        yield self._event(
            "status",
            {
                "status": "executing",
                "tool": "consult_coding_agent" if packet.mode == "consult" else "delegate_to_coding_agent",
                "tool_call_id": task.task_id,
            },
            outer_run_id,
        )

        result: ResultPacket
        child_events: List[Dict[str, Any]] = []
        started_at = time.time()
        if packet.mode == "consult":
            result, child_events = await run_consult_worker(packet, run_id=collab_run.run_id, task_id=task.task_id)
            for event in child_events:
                yield event
        else:
            async for event in run_execute_agent_events(
                packet,
                session_id=self.session_id,
                run_id=collab_run.run_id,
            ):
                child_events.append(event)
                yield event
            result = result_from_execute_events(child_events)

        task_status = "completed" if result.status == "pass" else ("blocked" if result.status == "blocked" else "failed")
        collab_update_task(task.task_id, status=task_status, result=result)
        collab_record_event(
            collab_run.run_id,
            "agent_message",
            {
                "run_id": collab_run.run_id,
                "agent_type": "coding",
                "text": result.summary or result.details,
                "status": result.status,
            },
            task.task_id,
        )
        if result.artifacts:
            for artifact in result.artifacts:
                collab_record_event(
                    collab_run.run_id,
                    "artifact_ready",
                    {
                        "run_id": collab_run.run_id,
                        "artifact": artifact.model_dump(),
                        "status": result.status,
                    },
                    task.task_id,
                )
        collab_complete_run(
            collab_run.run_id,
            "completed" if result.status == "pass" else "failed",
            result.summary or result.details,
            artifacts=result.artifacts,
        )
        for event in new_collab_events():
            yield event

        prefix = "Coding Agent 诊断结果" if packet.mode == "consult" else "Coding Agent 执行结果"
        status_word = "通过" if result.status == "pass" else ("受阻" if result.status == "blocked" else "未通过")
        summary = (result.summary or result.details or "Coding Agent 没有返回可用摘要。").strip()
        yield self._event(
            "tool_call",
            {
                "name": "consult_coding_agent" if packet.mode == "consult" else "delegate_to_coding_agent",
                "args": {"goal": packet.goal, "mode": packet.mode},
                "result": summary,
                "tool_call_id": task.task_id,
                "duration_ms": round((time.time() - started_at) * 1000),
            },
            outer_run_id,
        )
        final_text = f"{prefix}（{status_word}）：\n\n{summary}"
        assistant_msg = {"role": "assistant", "content": final_text}
        self._stamp_message(assistant_msg, turn_id=active_turn_id, checkpoint_id=active_checkpoint_id)
        self.messages.append(assistant_msg)
        self._trim_messages()
        yield self._event("content", {"text": final_text}, outer_run_id)
        yield self._event("context_usage", self.context_usage(), outer_run_id)
        yield self._event("status", {"status": "completed"}, outer_run_id)
        yield self._event("run_completed", {
            "status": "completed" if result.status == "pass" else "failed",
            "summary": final_text[:1000],
            "verification_passed": result.verification_passed,
            "review_passed": result.review_passed,
            "collaboration_run_id": collab_run.run_id,
            "collaboration_task_id": task.task_id,
        }, outer_run_id)
        self._save()

    def _stamp_message(
        self,
        message: Dict[str, Any],
        *,
        turn_id: str | None = None,
        checkpoint_id: str | None = None,
        created_at: float | None = None,
    ) -> Dict[str, Any]:
        message.setdefault("message_id", f"msg_{uuid.uuid4().hex[:16]}")
        message.setdefault("created_at", created_at or time.time())
        if turn_id:
            message.setdefault("turn_id", turn_id)
        if checkpoint_id:
            message.setdefault("checkpoint_id", checkpoint_id)
        return message

    def _ensure_message_metadata(self) -> None:
        current_turn = ""
        current_checkpoint = ""
        for msg in self.messages:
            role = msg.get("role")
            if role == "user":
                current_turn = msg.get("turn_id") or f"turn_{uuid.uuid4().hex[:12]}"
                current_checkpoint = msg.get("checkpoint_id") or f"chk_{uuid.uuid4().hex[:12]}"
                self._stamp_message(msg, turn_id=current_turn, checkpoint_id=current_checkpoint)
            elif role == "assistant" or role == "tool":
                self._stamp_message(
                    msg,
                    turn_id=msg.get("turn_id") or current_turn or None,
                    checkpoint_id=msg.get("checkpoint_id") or current_checkpoint or None,
                )
            else:
                self._stamp_message(msg)

    def _messages_for_llm(self, messages: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Strip local session/checkpoint metadata before sending to providers."""
        safe_messages: list[dict[str, Any]] = []
        for msg in messages or self.messages:
            safe = {k: copy.deepcopy(v) for k, v in msg.items() if k in _LLM_MESSAGE_KEYS}
            safe_messages.append(safe)
        return safe_messages

    def _active_turn_metadata(self) -> tuple[str, str]:
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                turn_id = msg.get("turn_id") or f"turn_{uuid.uuid4().hex[:12]}"
                checkpoint_id = msg.get("checkpoint_id") or f"chk_{uuid.uuid4().hex[:12]}"
                self._stamp_message(msg, turn_id=turn_id, checkpoint_id=checkpoint_id)
                return turn_id, checkpoint_id
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        return turn_id, f"chk_{uuid.uuid4().hex[:12]}"

    def _model_context_limit(self) -> int:
        try:
            provider_info = get_provider_for_model(self.model_id)
            if provider_info:
                _provider_name, provider = provider_info
                for model in provider.models:
                    if model.id == self.model_id:
                        return max(1, int(model.context))
        except Exception:
            pass
        return 32000

    def _completion_max_tokens(self) -> int:
        try:
            provider_info = get_provider_for_model(self.model_id)
            provider_name = provider_info[0] if provider_info else ""
            if provider_name == "kimi" and self._agent_type == "personal":
                return 2048
        except Exception:
            pass
        return 8192

    def _update_usage_from_response(self, response: Dict[str, Any] | None) -> None:
        usage = response.get("usage") if isinstance(response, dict) else None
        if isinstance(usage, dict) and usage:
            self._last_usage = usage

    def context_usage(self) -> Dict[str, Any]:
        self._ensure_message_metadata()
        context_limit = self._model_context_limit()
        breakdown = {
            "system": 0,
            "history": 0,
            "tools": 0,
            "rag": 0,
            "screenshots": 0,
            "tool_schemas": 0,
        }

        for msg in self.messages:
            role = msg.get("role")
            content = msg.get("content")
            tokens = _estimate_tokens(content)
            if role == "system":
                text = _text_from_content(content)
                if "Relevant Knowledge Base Context" in text:
                    breakdown["rag"] += tokens
                else:
                    breakdown["system"] += tokens
            elif role == "tool":
                breakdown["tools"] += tokens
            else:
                breakdown["history"] += tokens
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        breakdown["screenshots"] += 1200

        try:
            schemas = self._filter_tool_schemas_for_plan(
                get_tool_schemas(self.dynamic_registry, agent_type=self._agent_type)
            )
            breakdown["tool_schemas"] = _estimate_tokens(json.dumps(schemas, ensure_ascii=False))
        except Exception:
            breakdown["tool_schemas"] = 0

        estimate = sum(breakdown.values())
        provider_input = _usage_input_tokens(self._last_usage)
        provider_output = _usage_output_tokens(self._last_usage)
        exact = provider_input > 0
        used_tokens = provider_input + provider_output if exact else estimate
        used_percent = min(100.0, round((used_tokens / context_limit) * 100, 1))
        status = "critical" if used_percent >= 85 else "warning" if used_percent >= 70 else "ok"
        payload = {
            "session_id": self.session_id,
            "model_id": self.model_id,
            "model_context": context_limit,
            "estimated_tokens": estimate,
            "used_tokens": used_tokens,
            "output_tokens": provider_output,
            "remaining_tokens": max(0, context_limit - used_tokens),
            "used_percent": used_percent,
            "exact": exact,
            "source": "provider" if exact else "estimate",
            "status": status,
            "breakdown": breakdown,
        }
        self._last_context_usage = payload
        return payload

    def build_checkpoints(self) -> List[Dict[str, Any]]:
        self._ensure_message_metadata()
        checkpoints: list[dict[str, Any]] = []
        for index, msg in enumerate(self.messages):
            if msg.get("role") != "user":
                continue
            if msg.get("source") == "internal":
                continue
            text = _text_from_content(msg.get("content", "")).strip()
            checkpoints.append({
                "id": msg.get("checkpoint_id"),
                "message_id": msg.get("message_id"),
                "turn_id": msg.get("turn_id"),
                "index": index,
                "role": "user",
                "preview": text[:180] if text else "(image or empty prompt)",
                "created_at": msg.get("created_at") or time.time(),
            })
        return checkpoints

    def rewind_to_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_message_metadata()
        target_index = -1
        target: Dict[str, Any] | None = None
        for index, msg in enumerate(self.messages):
            if msg.get("role") == "user" and msg.get("checkpoint_id") == checkpoint_id:
                target_index = index
                target = msg
                break
        if target_index < 0 or target is None:
            return None
        self.messages = self.messages[:target_index + 1]
        self.iteration = 0
        self._cancelled = False
        self._last_user_message = _text_from_content(target.get("content", ""))
        self._refresh_system_prompt()
        self._save()
        return {
            "checkpoint_id": checkpoint_id,
            "message_id": target.get("message_id"),
            "preview": _text_from_content(target.get("content", ""))[:180],
            "context_usage": self.context_usage(),
        }

    def _trim_messages(self):
        """Trim history without splitting assistant tool_calls from their tool results."""
        self.messages = trim_messages(
            self.messages,
            self.MAX_HISTORY_MESSAGES,
            build_system_prompt_fn=self._build_system_prompt,
            validate_tool_ids=True,
        )

    def _plan_event_payload(self) -> Dict[str, Any]:
        return {
            "mode": self.plan_state.mode,
            "phase": self.plan_state.phase,
            "approved": self.plan_state.approved,
            "draft": self.plan_state.draft,
            "goal": self.plan_state.goal,
            "pending_clarification": self.plan_state.pending_clarification,
            "structured_plan": self.plan_state.structured_plan.model_dump() if self.plan_state.structured_plan else None,
            "questions": [q.model_dump() for q in self.plan_state.questions],
            "todos": [t.model_dump() for t in self.plan_state.todos],
            "decisions": self.plan_state.decisions,
            "decision_notes": self.plan_state.decision_notes,
            "plan_file_path": self.plan_state.plan_file_path,
            "research_notes": self.plan_state.research_notes,
        }

    def plan_event_payload(self) -> Dict[str, Any]:
        """Snapshot for WebSocket `plan_*` events."""
        return self._plan_event_payload()

    def set_session_chat_mode(self, mode: str) -> bool:
        """Persist UI-selected agent/plan mode before the next chat message (WebSocket `set_chat_mode`)."""
        if mode not in ("agent", "plan"):
            return False
        previous = self.chat_mode
        self.chat_mode = mode
        if mode == "plan" and previous != "plan":
            if self.plan_state.phase != "executing":
                self.plan_state = PlanState(mode="plan")
                self._plan_exec_hint_sent = False
            else:
                self.plan_state.mode = "plan"
        elif mode == "agent" and previous == "plan":
            if self.plan_state.phase != "executing":
                self.plan_state = PlanState(mode="agent")
                self._plan_exec_hint_sent = False
            else:
                self.plan_state.mode = "agent"
        else:
            self.plan_state.mode = mode
        self._save()
        return True

    def set_session_thinking_intensity(self, intensity: str) -> bool:
        """Persist UI-selected thinking intensity for the active agent."""
        if intensity not in ("low", "medium", "high"):
            return False
        self.thinking_intensity = intensity
        self._agent_thinking[self._agent_type] = intensity
        self._save()
        return True

    # Tools that can break out of the current project context.
    _CONTEXT_ESCAPE_TOOLS: frozenset[str] = frozenset({"git_clone", "browser_navigate"})
    _EXTERNAL_RESOURCE_KEYWORDS = [
        "clone", "github", "gitlab", "gitee", "bitbucket",
        "repo", "repository", "template", "模板",
        "url", "http", "下载", "download",
        "外部", "external", "website", "网站",
        "浏览", "browse", "navigate", "打开网页",
    ]

    def _is_readonly_plan_tool(self, tool_name: str) -> bool:
        if not tool_name or tool_name.startswith("mcp_"):
            return False
        return tool_name in READONLY_PLAN_TOOLS

    def _check_tool_intent_consistency(
        self, tool_name: str, tool_args: Dict[str, Any], user_input: str
    ) -> Tuple[bool, str]:
        """Block hallucinated calls to external-resource tools when the user did not ask for them."""
        if tool_name not in self._CONTEXT_ESCAPE_TOOLS:
            return True, ""

        user_lower = (user_input or "").lower()
        # Localhost navigations are always allowed (common dev workflow)
        if tool_name == "browser_navigate":
            url = str(tool_args.get("url") or "").lower()
            if "localhost" in url or "127.0.0.1" in url:
                return True, ""

        # Check if user explicitly mentioned external resources
        has_external_intent = any(kw in user_lower for kw in self._EXTERNAL_RESOURCE_KEYWORDS)
        if not has_external_intent:
            return False, (
                f"[INTENT_BLOCKED] The tool `{tool_name}` accesses external resources, "
                f"but the user request does not mention cloning, external URLs, or browsing. "
                f"If this is intentional, please rephrase your request to explicitly mention the external resource."
            )
        return True, ""

    _PLAN_PHASE_TOOLS: frozenset[str] = frozenset({"plan_ask_questions", "plan_write_draft"})

    def _filter_tool_schemas_for_plan(self, schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self.chat_mode != "plan" or self.plan_state.approved:
            return schemas
        return [
            s for s in schemas
            if self._is_readonly_plan_tool((s.get("function") or {}).get("name", ""))
            or (s.get("function") or {}).get("name", "") in self._PLAN_PHASE_TOOLS
        ]

    def _build_plan_draft_text(self, user_input: str) -> str:
        """Fallback four-block plan text (used only if writing the plan file
        fails). Mirrors plan_files._render_markdown's structure."""
        if not self.plan_state.structured_plan:
            return ""
        plan = self.plan_state.structured_plan
        lines = [
            f"# {plan.goal or user_input.strip()[:800]}",
            "",
            "## 任务目标 / Goal",
            (plan.context.strip() or plan.goal.strip() or user_input.strip()[:800]),
            "",
            "## 任务方案 / Approach",
        ]
        for i, t in enumerate(plan.todos, 1):
            deps = f" (depends: {', '.join(t.depends_on)})" if t.depends_on else ""
            grp = f" [{t.parallel_group}]" if t.parallel_group else ""
            lines.append(f"### PART {i} — {t.title}{deps}{grp}")
            if t.acceptance_criteria:
                lines.append(f"- 验收 / Acceptance: {t.acceptance_criteria}")
        lines.extend(["", "## 关键文件清单 / Critical Files"])
        if plan.critical_files:
            for cf in plan.critical_files:
                path = str(cf.get("path", "")).strip()
                if not path:
                    continue
                change = str(cf.get("change", "")).strip()
                lines.append(f"- `{path}`" + (f" — {change}" if change else ""))
        else:
            lines.append("_探索阶段确认 / determined during exploration_")
        lines.extend(["", "## 验证 / Verification"])
        if plan.acceptance_criteria:
            for item in plan.acceptance_criteria:
                lines.append(f"- {item}")
        else:
            lines.append("- _见各 PART 的验收标准 / see each PART's acceptance criteria_")
        return "\n".join(lines)

    def _inject_plan_execution_hint(self) -> None:
        if self._plan_exec_hint_sent or not self.plan_state.approved:
            return
        cfg = load_config().settings
        mode = getattr(cfg, "collaboration_mode", "serial") or "serial"
        lines = [
            "[Plan execution — the user clicked Build]",
            "The user clicked Build. This is FULL APPROVAL of the plan below. "
            "Do NOT ask any further clarifying questions, do NOT re-confirm any decisions, "
            "do NOT restate or rewrite the plan. Begin executing the first todo immediately. "
            "For any open questions left in the plan, proceed using the assumptions/defaults "
            "recorded in the plan; only mark a todo as blocked (with a reason) if you hit a real blocker.",
            "",
            "[Follow the approved plan below]",
            f"Collaboration mode: {mode}. Max parallel agents: {getattr(cfg, 'max_parallel_agents', 3)}.",
        ]
        if mode == "parallel":
            lines.append(
                "For todos with the same parallel_group, prefer dispatch_parallel with one task per worker."
            )
        elif mode == "hybrid":
            lines.append(
                "Serialize implementation on the critical path; use dispatch_parallel for independent analysis or verification todos."
            )
        else:
            lines.append("Run todos mostly serially; use dispatch_worker for focused subtasks.")

        # Inject the approved plan markdown (truncated to avoid context bloat).
        plan_md = self.plan_state.draft
        if not plan_md and self.plan_state.plan_file_path:
            try:
                plan_md = read_plan_file(self.session_id, ntpath.basename(self.plan_state.plan_file_path))
            except Exception:
                pass
        max_plan_len = 8000
        if len(plan_md) > max_plan_len:
            plan_md = plan_md[:max_plan_len] + "\n\n[Plan truncated — full version available via file_read]"
        if plan_md:
            lines.append("")
            lines.append(plan_md)

        lines.append("")
        lines.append("## Execution Rules — drive the todo list explicitly (like Claude Code)")
        lines.append(
            "- Work the todos in dependency order, ONE at a time. Before you start a "
            "todo, call `plan_update_todos` to set it `in_progress`."
        )
        lines.append(
            "- The MOMENT a todo is done, call `plan_update_todos` to set it "
            "`completed` (you may set the next todo `in_progress` in the SAME call). "
            "Do NOT batch many completions at the end — the user watches progress "
            "tick item-by-item, so update after EACH todo finishes."
        )
        lines.append(
            "- If you hit a real blocker, call `plan_update_todos` to set that todo "
            "`blocked` with a `note` explaining why, then continue with todos that "
            "don't depend on it."
        )
        lines.append("- After implementation, run verify_project and git_diff for review.")
        lines.append(
            "- Optional: if you delegate a todo via dispatch_worker, include its "
            "acceptance_criteria in the task and ask the worker to end with exactly "
            "`ACCEPTANCE: PASS` or `ACCEPTANCE: FAIL`; only mark it `completed` on PASS. "
            "Direct execution is fine too — either way, you MUST keep the todo "
            "statuses current via `plan_update_todos`."
        )
        self.messages.append({"role": "system", "content": "\n".join(lines)})
        self._plan_exec_hint_sent = True

    @staticmethod
    def _looks_like_stale_build_prompt(text: str) -> bool:
        normalized = (text or "").lower()
        if not normalized.strip():
            return False
        stale_terms = (
            "click build",
            "press build",
            "tap build",
            "select build",
            "hit build",
            "ready to build",
            "wait for build",
            "waiting for build",
            "plan is ready",
            "plan generated",
            "点击 build",
            "点 build",
            "按 build",
            "选择 build",
            "等待 build",
            "准备 build",
            "计划已生成",
            "计划已经生成",
            "计划已提交",
        )
        if any(term in normalized for term in stale_terms):
            return True
        return "build" in normalized and any(term in normalized for term in ("click", "press", "ready", "waiting", "approve"))

    def _append_build_already_clicked_correction(self, turn_id: str, checkpoint_id: str) -> None:
        msg = {
            "role": "user",
            "source": "internal",
            "content": (
                "[BUILD ALREADY CLICKED] The user already clicked Build and the plan is approved. "
                "Do not ask the user to click Build again, do not restate the plan, and do not wait. "
                "Immediately execute the first pending/in-progress task using the available tools. "
                "If a task is genuinely blocked, mark it blocked with the concrete reason."
            ),
        }
        self._stamp_message(msg, turn_id=turn_id, checkpoint_id=checkpoint_id)
        self.messages.append(msg)

    def _start_plan_execution(self) -> None:
        self.plan_state.transition_to("executing")
        self._plan_exec_hint_sent = False
        for todo in self.plan_state.todos:
            if todo.status == "in_progress":
                return
        for todo in self.plan_state.todos:
            if todo.status == "pending":
                todo.status = "in_progress"
                break

    def approve_plan(self) -> None:
        """Deprecated: kept for old session compatibility. Use build_plan() directly."""
        self.plan_state.approved = True
        self.plan_state.transition_to("approved_waiting_build")
        self._save()

    def reject_plan(self) -> None:
        self.plan_state.approved = False
        self.plan_state.pending_clarification = False
        self.plan_state.transition_to("clarifying")
        self._plan_exec_hint_sent = False
        self._save()

    def build_plan(self) -> bool:
        """One-click Build: approves + starts execution + switches to agent mode."""
        if self.plan_state.phase == "executing" and self.plan_state.approved:
            self.chat_mode = "agent"
            self.plan_state.mode = "agent"
            self._save()
            return True
        has_plan = bool(self.plan_state.draft or self.plan_state.structured_plan or self.plan_state.todos)
        valid_phase = self.plan_state.phase in ("awaiting_approval", "approved_waiting_build")
        if not valid_phase and has_plan and self.plan_state.phase not in ("executing", "completed"):
            self.plan_state.phase = "awaiting_approval"
            valid_phase = True
        if not valid_phase:
            return False
        self.plan_state.approved = True
        self._start_plan_execution()
        # Auto-switch to agent mode so subsequent messages don't re-enter plan flow.
        self.chat_mode = "agent"
        self._save()
        return True

    def restore_plan_state_snapshot(self, payload: Dict[str, Any]) -> bool:
        """Restore a UI-held plan snapshot when a Build click races session state."""
        if not isinstance(payload, dict):
            return False
        try:
            restored = PlanState.model_validate(payload)
        except Exception:
            return False
        has_plan = bool(restored.draft or restored.structured_plan or restored.todos)
        if not has_plan or restored.phase not in ("awaiting_approval", "approved_waiting_build", "executing"):
            return False
        restored.approved = restored.phase in ("approved_waiting_build", "executing")
        restored.pending_clarification = False
        self.plan_state = restored
        self.chat_mode = "agent" if restored.phase == "executing" else "plan"
        self.plan_state.mode = self.chat_mode
        self._save()
        return True

    def pause_plan_build(self) -> bool:
        """Pause Build execution so the user can resume from the next unfinished todo."""
        if self.plan_state.phase != "executing":
            return False
        for todo in self.plan_state.todos:
            if todo.status == "in_progress":
                todo.status = "pending"
        self.plan_state.approved = True
        self.plan_state.pending_clarification = False
        self._plan_exec_hint_sent = False
        self.chat_mode = "agent"
        self.plan_state.mode = "agent"
        self.plan_state.phase = "approved_waiting_build"
        self._save()
        return True

    def exit_plan_build(self) -> bool:
        """End Build execution while keeping the draft available for review/rebuild."""
        if self.plan_state.phase not in ("executing", "approved_waiting_build"):
            return False
        for todo in self.plan_state.todos:
            if todo.status in ("pending", "in_progress"):
                todo.status = "cancelled"
        self.plan_state.approved = False
        self.plan_state.pending_clarification = False
        self._plan_exec_hint_sent = False
        self.chat_mode = "plan" if (self.plan_state.draft or self.plan_state.structured_plan) else "agent"
        self.plan_state.mode = self.chat_mode
        self.plan_state.phase = (
            "awaiting_approval"
            if (self.plan_state.draft or self.plan_state.structured_plan)
            else "idle"
        )
        self._save()
        return True

    def _plan_question_has_answer(self, question_id: str) -> bool:
        return bool(self.plan_state.decisions.get(question_id)) or bool(self.plan_state.decision_notes.get(question_id))

    def _continue_after_plan_decisions(self) -> None:
        if self.plan_state.phase != "awaiting_decision":
            self._save()
            return

        all_answered = all(self._plan_question_has_answer(q.id) for q in self.plan_state.questions)
        if not all_answered:
            self._save()
            return

        # Feed decisions back to the LLM so it can synthesize a researched plan.
        lines = ["[User answered the plan clarification questions:]"]
        for q in self.plan_state.questions:
            picks = self.plan_state.decisions.get(q.id, [])
            label_by_id = {o.id: o.label for o in q.options}
            labels = [label_by_id.get(p, p) for p in picks]
            note = (self.plan_state.decision_notes.get(q.id) or "").strip()
            answer_parts = []
            if labels:
                answer_parts.append(", ".join(labels))
            if note:
                answer_parts.append(note)
            if not answer_parts:
                answer_parts.append("Skipped; use the best default and state the assumption in the plan.")
            lines.append(f"- {q.prompt} => {'; '.join(answer_parts)}")
        lines.append("")
        lines.append("Please synthesize these decisions with your research and call plan_write_draft.")
        msg = {"role": "user", "content": "\n".join(lines), "source": "internal"}
        turn_id, checkpoint_id = self._active_turn_metadata()
        self._stamp_message(msg, turn_id=turn_id, checkpoint_id=checkpoint_id)
        self.messages.append(msg)
        self.plan_state.pending_clarification = False
        self.plan_state.questions = []
        self.plan_state.transition_to("planning")
        self._save()

    def update_plan_decision(self, question_id: str, selected: List[str]) -> None:
        self.submit_plan_decisions([{
            "question_id": question_id,
            "selected": selected,
        }])

    def submit_plan_decisions(self, answers: List[Dict[str, Any]]) -> None:
        """Apply one or more structured plan answers and resume planning once all are answered."""
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            question_id = str(answer.get("question_id") or answer.get("questionId") or "").strip()
            if not question_id:
                continue

            selected_raw = answer.get("selected") or []
            if not isinstance(selected_raw, list):
                selected_raw = [selected_raw]
            selected = [
                str(item)
                for item in selected_raw
                if item is not None and str(item).strip() and str(item) != "__other__"
            ]
            self.plan_state.decisions[question_id] = selected

            notes: List[str] = []
            other_text = str(answer.get("other_text") or answer.get("otherText") or "").strip()
            if other_text:
                notes.append(f"Other: {other_text}")
            if bool(answer.get("skipped", False)):
                notes.append("Skipped; use the best default and state the assumption in the plan.")
            if notes:
                self.plan_state.decision_notes[question_id] = "; ".join(notes)
            else:
                self.plan_state.decision_notes.pop(question_id, None)

        self._continue_after_plan_decisions()

    # ── LLM-driven plan tool application ──

    _PLAN_OPTION_LINE_RE = re.compile(
        r"^\s*(?:[-*]\s*)?(?:(?:\d{1,2})|(?:[A-Ha-h]))[\.\)、)]\s+(?P<label>.+?)\s*$"
    )

    @staticmethod
    def _clean_plan_choice_text(text: str) -> str:
        cleaned = re.sub(r"`([^`]+)`", r"\1", str(text))
        cleaned = cleaned.replace("**", "").replace("__", "")
        cleaned = re.sub(r"(?:选项|options?|choices?)\s*[:：]\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" \t:-")

    def _extract_plan_questions_from_text(self, text: str) -> List[Dict[str, Any]]:
        """Best-effort guardrail for models that print fixed options instead of calling plan_ask_questions."""
        if not text or len(text) > 12000:
            return []

        lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
        option_start = -1
        raw_options: List[str] = []

        i = 0
        while i < len(lines):
            match = self._PLAN_OPTION_LINE_RE.match(lines[i])
            if not match:
                i += 1
                continue

            current: List[str] = []
            start = i
            while i < len(lines):
                option_match = self._PLAN_OPTION_LINE_RE.match(lines[i])
                if not option_match:
                    break
                label = self._clean_plan_choice_text(option_match.group("label"))
                if label:
                    current.append(label)
                i += 1

            if len(current) >= 2:
                option_start = start
                raw_options = current[:5]
                break
            i = start + 1

        if option_start < 0 or len(raw_options) < 2:
            return []

        nearby_before = lines[max(0, option_start - 4):option_start]
        has_choice_cue = any(
            re.search(r"(选项|可选|选择|options?|choices?|choose|select)", line, re.IGNORECASE)
            for line in nearby_before
        )
        has_question_cue = any(("?" in line or "？" in line) for line in nearby_before)
        if not has_choice_cue and not has_question_cue:
            return []

        prompt_candidates: List[str] = []
        j = option_start - 1
        while j >= 0 and len(prompt_candidates) < 4:
            line = lines[j]
            if not line:
                if prompt_candidates:
                    break
                j -= 1
                continue
            if re.fullmatch(r"(?:选项|options?|choices?)\s*[:：]?", line, flags=re.IGNORECASE):
                j -= 1
                continue
            if not self._PLAN_OPTION_LINE_RE.match(line):
                prompt_candidates.append(line)
            j -= 1

        prompt_candidates.reverse()
        prompt = ""
        for candidate in reversed(prompt_candidates):
            if "?" in candidate or "？" in candidate:
                prompt = candidate
                break
        if not prompt and prompt_candidates:
            prompt = prompt_candidates[-1]
        if not prompt:
            prompt = "Please choose one option before I draft the plan."

        return [{
            "id": "clarification_1",
            "prompt": self._clean_plan_choice_text(prompt),
            "allow_multiple": False,
            "options": [
                {"id": f"option_{idx + 1}", "label": label}
                for idx, label in enumerate(raw_options)
            ],
        }]

    def _apply_plan_questions(self, raw_questions: List[Dict[str, Any]]) -> None:
        """Apply questions submitted by the LLM via plan_ask_questions tool."""
        qs: List[PlanQuestion] = []
        for rq in raw_questions:
            opts = [PlanQuestionOption(id=o["id"], label=o["label"]) for o in rq.get("options", [])]
            qs.append(PlanQuestion(
                id=rq["id"],
                prompt=rq["prompt"],
                allow_multiple=rq.get("allow_multiple", False),
                options=opts,
            ))
        self.chat_mode = "plan"
        self.plan_state.mode = "plan"
        if self.plan_state.phase in ("idle", "completed"):
            self.plan_state.transition_to("clarifying")
        self.plan_state.questions = qs
        self.plan_state.decisions = {}
        self.plan_state.decision_notes = {}
        self.plan_state.pending_clarification = True
        if not self.plan_state.transition_to("awaiting_decision"):
            self.plan_state.phase = "awaiting_decision"
        self._save()

    def _apply_plan_draft(self, payload: Dict[str, Any]) -> None:
        """Apply a draft submitted by the LLM via plan_write_draft tool."""
        # Build structured plan from payload
        from app.workflow.models import PlanStep
        steps = [
            PlanStep(
                id=s.get("id", f"step_{i}"),
                title=s.get("title", ""),
                details=s.get("details", ""),
                depends_on=s.get("depends_on", []) or [],
                parallel_group=s.get("parallel_group"),
            )
            for i, s in enumerate(payload.get("steps", []))
        ]
        todos = [
            PlanTodo(
                id=t.get("id", f"todo_{i}"),
                title=t.get("title", ""),
                status="pending",
                depends_on=t.get("depends_on", []) or [],
                parallel_group=t.get("parallel_group"),
                acceptance_criteria=t.get("acceptance_criteria", ""),
            )
            for i, t in enumerate(payload.get("todos", []))
        ]
        critical_files = [
            {"path": str(cf.get("path", "")), "change": str(cf.get("change", ""))}
            for cf in (payload.get("critical_files", []) or [])
            if isinstance(cf, dict) and cf.get("path")
        ]
        draft = PlanDraft(
            goal=payload.get("goal", ""),
            context=payload.get("context", "") or "",
            assumptions=payload.get("assumptions", []) or [],
            steps=steps,
            todos=todos,
            risks=payload.get("risks", []) or [],
            acceptance_criteria=payload.get("verification", []) or [],
            critical_files=critical_files,
        )

        self.chat_mode = "plan"
        self.plan_state.mode = "plan"
        self.plan_state.structured_plan = draft
        self.plan_state.todos = todos

        # Persist the canonical task-first markdown file and use it for review.
        # Model-provided markdown_body is ignored here to prevent duplicate
        # Steps/Todos sections from leaking back into the user-facing plan.
        draft_text = ""

        # Persist plan file
        research_notes = payload.get("research_notes", "")
        self.plan_state.research_notes = research_notes
        try:
            path = write_plan_file(
                self.session_id,
                draft,
                raw_markdown=payload.get("markdown_body", ""),
                research_notes=research_notes,
            )
            self.plan_state.plan_file_path = str(path)
            if self.plan_state.plan_file_path not in self.plan_state.plan_file_versions:
                self.plan_state.plan_file_versions.append(self.plan_state.plan_file_path)
            draft_text = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to write plan file: %s", e)
            if not draft_text.strip():
                draft_text = self._build_plan_draft_text(payload.get("goal", ""))

        self.plan_state.draft = draft_text
        self.plan_state.pending_clarification = False
        if self.plan_state.phase in ("idle", "completed"):
            self.plan_state.transition_to("planning")
        if not self.plan_state.transition_to("awaiting_approval"):
            self.plan_state.phase = "awaiting_approval"
        self.plan_state.approved = False
        self._save()

    async def run(
        self,
        user_input: str,
        image_base64: Optional[str] = None,
        *,
        chat_mode: Optional[str] = None,
        thinking_intensity: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run one agent turn. Empty user_input means retry mode.

        ``PLAN_CONTINUE_MARKER`` resumes execution after the user clicks Build (server-gated).
        """
        if chat_mode in ("agent", "plan"):
            if chat_mode != self.chat_mode:
                self.set_session_chat_mode(chat_mode)
            else:
                self.chat_mode = chat_mode
        if thinking_intensity in ("low", "medium", "high"):
            self.set_session_thinking_intensity(thinking_intensity)

        self.iteration = 0
        self._cancelled = False
        self._repo_map_cache = None
        run_id = f"{self.session_id}-{uuid.uuid4().hex[:12]}"
        ti = self.thinking_intensity
        coding_run = None
        run_context_token = None
        coding_run_closed = False

        is_plan_continue = user_input == PLAN_CONTINUE_MARKER

        try:
            coding_run = None
            if self._agent_type == "coding":
                coding_run = create_coding_run(
                    session_id=self.session_id,
                    run_id=run_id,
                    prompt=self._last_user_message if is_plan_continue else user_input,
                )
            if coding_run:
                run_context_token = set_run_context(coding_run)
                yield self._event(
                    "run_created",
                    {
                        "project_path": coding_run.project_path,
                        "mode": coding_run.mode,
                        "worktree_path": coding_run.worktree_path,
                        "base_branch": coding_run.base_branch,
                        "base_commit": coding_run.base_commit,
                    },
                    run_id,
                )
                if load_config().coding_agent.auto_generate_repo_map:
                    if self._repo_map_cache is not None:
                        repo_map = self._repo_map_cache
                    else:
                        repo_map = build_repo_map(coding_run.active_path)
                        self._repo_map_cache = repo_map
                    context_payload = {
                        "repo_map_summary": format_repo_map_summary(repo_map, max_chars=5000),
                        "commands": repo_map.get("commands", []),
                        "files": repo_map.get("files", [])[:80],
                    }
                    record_event(run_id, "context_pack", context_payload)
                    yield self._event("context_pack", context_payload, run_id)
        except Exception as e:
            logger.warning("Coding run initialization failed: %s", e)

        def close_coding_run(status: str, summary: str = "", details: Optional[Dict[str, Any]] = None) -> None:
            nonlocal coding_run_closed, run_context_token
            if coding_run and not coding_run_closed:
                complete_run(run_id, status, summary, details=details)
                coding_run_closed = True
            if run_context_token is not None:
                reset_run_context(run_context_token)
                run_context_token = None

        if user_input and not is_plan_continue:
            if self.chat_mode == "plan" and self.plan_state.phase == "awaiting_decision":
                yield self._event(
                    "error",
                    {"message": "Plan mode: answer the key decision questions before sending a new message."},
                    run_id,
                )
                yield self._event("status", {"status": "completed"}, run_id)
                yield self._event("run_completed", {
                    "status": "completed",
                    "summary": "Plan mode is awaiting decisions.",
                    "verification_passed": None,
                    "review_passed": None,
                }, run_id)
                close_coding_run("completed", "Plan mode is awaiting decisions.")
                self._save()
                return

            # Resolve @mentions in user input (file/folder/git/knowledge context)
            project = ProjectManager.get_current()
            project_path = project["path"] if project else ""
            resolved_input = resolve_mentions(user_input, project_path) if project_path else user_input

            # Explicit delegation has priority over Personal's normal reasoning turn.
            settings = load_config().settings
            coding_mention = parse_coding_mention(user_input)
            if (
                self._agent_type == "personal"
                and self.chat_mode != "plan"
                and getattr(settings, "collaboration_enabled", True)
                and coding_mention is not None
            ):
                self._last_user_message = user_input
                async for event in self._handle_coding_mention(
                    coding_mention,
                    original_input=user_input,
                    resolved_input=resolved_input,
                    image_base64=image_base64,
                    outer_run_id=run_id,
                ):
                    yield event
                close_coding_run("completed", "Explicit Coding Agent delegation handled.")
                return

            # Auto-dispatch: Personal Agent detects code intent → suggest switching to Coding
            if self._agent_type == "personal" and project and self.chat_mode != "plan":
                if not getattr(self, "_dispatch_suggested_this_session", False):
                    if AgentSession._detect_code_intent(user_input):
                        inferred_mode = classify_coding_intent(user_input)
                        auto_delegate = getattr(settings, "auto_delegate_coding", "suggest") or "suggest"
                        should_auto_delegate = (
                            auto_delegate == "always_for_code"
                            or (auto_delegate == "safe_only" and inferred_mode == "consult")
                        )
                        if should_auto_delegate and getattr(settings, "collaboration_enabled", True):
                            self._dispatch_suggested_this_session = True
                            synthetic_mention = CodingMention(
                                raw="@coding agent",
                                task=user_input,
                                mode="execute" if inferred_mode == "execute" else "consult",
                            )
                            self._last_user_message = user_input
                            async for event in self._handle_coding_mention(
                                synthetic_mention,
                                original_input=user_input,
                                resolved_input=resolved_input,
                                image_base64=image_base64,
                                outer_run_id=run_id,
                            ):
                                yield event
                            close_coding_run("completed", "Automatic Coding Agent delegation handled.")
                            return
                        self._dispatch_suggested_this_session = True
                        yield self._event(
                            "suggest_agent_switch",
                            {
                                "from": "personal",
                                "to": "coding",
                                "reason": "This task involves code development. The Coding Agent can take over the technical details automatically: inspect the project, make the change, run verification, review the result, and report in plain language.",
                            },
                            run_id,
                        )

            self._last_user_message = user_input  # Keep original for skill matching
            self._refresh_system_prompt()
            if self._rag_context_sources:
                yield self._event(
                    "knowledge_context",
                    {
                        "count": len(self._rag_context_sources),
                        "sources": self._rag_context_sources,
                    },
                    run_id,
                )
            active_turn_id = f"turn_{uuid.uuid4().hex[:12]}"
            active_checkpoint_id = f"chk_{uuid.uuid4().hex[:12]}"
            if image_base64:
                user_msg = self.router.build_vision_message(resolved_input, image_base64)
            else:
                user_msg = {"role": "user", "content": resolved_input}
            user_msg["source"] = "user"
            self._stamp_message(user_msg, turn_id=active_turn_id, checkpoint_id=active_checkpoint_id)
            self.messages.append(user_msg)
            self._trim_messages()
            yield self._event("context_usage", self.context_usage(), run_id)

            if self.chat_mode == "plan":
                is_new_plan = self.plan_state.phase in ("idle", "completed")
                if is_new_plan:
                    self.plan_state.mode = "plan"
                    self.plan_state.goal = user_input.strip()[:800]
                    self.plan_state.decisions = {}
                    self.plan_state.decision_notes = {}
                    self.plan_state.pending_clarification = False
                    self.plan_state.research_notes = ""
                    self.plan_state.structured_plan = None
                    self.plan_state.todos = []
                    self.plan_state.questions = []
                    self.plan_state.plan_file_path = None
                    self.plan_state.approved = False
                    self.plan_state.transition_to("clarifying")
                # else: continuing clarify conversation; goal/research preserved.
                yield self._event("plan_status", {**self._plan_event_payload(), "message": "clarifying"}, run_id)
                # LLM will drive the planning via plan_mode.md spec.
                # Fall through to the run loop below.

        elif is_plan_continue:
            if not self.plan_state.approved or self.plan_state.phase != "executing":
                yield self._event("error", {"message": "Plan is not ready to build yet."}, run_id)
                yield self._event("status", {"status": "completed"}, run_id)
                yield self._event("run_completed", {
                    "status": "completed",
                    "summary": "Plan is not ready to build yet.",
                    "verification_passed": None,
                    "review_passed": None,
                }, run_id)
                close_coding_run("completed", "Plan is not ready to build yet.")
                return
            self._inject_plan_execution_hint()
            if self.plan_state.todos:
                yield self._event("todo_update", {"todos": [t.model_dump() for t in self.plan_state.todos]}, run_id)

        active_turn_id, active_checkpoint_id = self._active_turn_metadata()

        active_skills: List[str] = []
        skills_trace = {"skills": [], "disabled_matches": []}
        if self._last_user_message:
            project = ProjectManager.get_current()
            skills_trace = SkillManager.explain_match_skills(
                self._last_user_message,
                self.role_id,
                project is not None,
                agent_type=self._agent_type,
            )
            active_skills = [skill["id"] for skill in skills_trace["skills"]]
        skills_payload = {
            "agent_type": self._agent_type,
            "skills": skills_trace.get("skills", []),
            "disabled_matches": skills_trace.get("disabled_matches", []),
        }
        if coding_run:
            record_event(run_id, "skills_matched", skills_payload)
        yield self._event("skills_matched", skills_payload, run_id)

        yield self._event("status", {"status": "thinking"}, run_id)

        finished = False
        plan_turn_done = False
        _files_modified = False
        _verify_called = False
        _unstructured_verification_seen = False
        _verify_gate_fired = False
        _latest_verification: Optional[Dict[str, Any]] = None
        _latest_review: Optional[Dict[str, Any]] = None
        stale_build_prompt_guarded = False
        while self.iteration < self.max_iterations:
            if self._cancelled:
                yield self._event("interrupted", {"message": "User cancelled"}, run_id)
                finished = True
                break

            self.iteration += 1

            if self.screenshot_on_step and self._should_screenshot():
                ss_tool = ScreenshotTool()
                ss_result = await ss_tool.execute()
                if ss_result.base64_image:
                    ss_content = [
                        {"type": "text", "text": "[System screenshot - current screen state]"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ss_result.base64_image}"}}
                    ]
                    if self.messages and self.messages[-1].get("role") == "user":
                        last_content = self.messages[-1].get("content", [])
                        if isinstance(last_content, list):
                            last_content.extend(ss_content)
                        else:
                            self.messages[-1]["content"] = [{"type": "text", "text": str(last_content)}] + ss_content
                    else:
                        screenshot_msg = {
                            "role": "user",
                            "content": ss_content,
                            "source": "internal",
                        }
                        self._stamp_message(
                            screenshot_msg,
                            turn_id=active_turn_id,
                            checkpoint_id=active_checkpoint_id,
                        )
                        self.messages.append(screenshot_msg)

            tool_schemas = self._filter_tool_schemas_for_plan(get_tool_schemas(self.dynamic_registry, agent_type=self._agent_type))
            completion_max_tokens = self._completion_max_tokens()

            # Stream LLM response token-by-token for real-time frontend display
            response = None
            stream_error = None
            streamed_reasoning_text = ""
            streamed_content_text = ""
            buffer_execution_content = self.plan_state.approved and self.plan_state.phase == "executing"
            streamed_content_visible = False
            try:
                async for token in self.router.chat_completion_stream(
                    messages=self._messages_for_llm(),
                    tools=tool_schemas or None,
                    temperature=0.5,
                    max_tokens=completion_max_tokens,
                    thinking_intensity=ti,
                ):
                    ttype = token.get("type", "")
                    if ttype == "thinking_delta":
                        streamed_reasoning_text += token["text"]
                        yield self._event(
                            "reasoning",
                            {"text": token["text"], "skill": active_skills[0] if active_skills else None},
                            run_id,
                        )
                    elif ttype == "text_delta":
                        streamed_content_text += token["text"]
                        if not buffer_execution_content:
                            streamed_content_visible = True
                            yield self._event(
                                "content",
                                {"text": token["text"], "skill": active_skills[0] if active_skills else None},
                                run_id,
                            )
                    elif ttype == "done":
                        response = token["response"]
                    elif ttype == "error":
                        stream_error = token.get("message", "Stream error")
            except Exception as e:
                stream_error = str(e)

            # Handle stream failure with non-streaming fallback
            if stream_error:
                error_msg = stream_error.lower()
                if "does not support tools" in error_msg or "tool" in error_msg.lower() or "tools" in error_msg.lower():
                    try:
                        response = await self.router.chat_completion_non_stream(
                            messages=self._messages_for_llm(),
                            temperature=0.5,
                            max_tokens=completion_max_tokens,
                            thinking_intensity=ti,
                        )
                        stream_error = None
                    except Exception as e2:
                        yield self._event("error", {"message": f"Model call failed: {e2}"}, run_id)
                        finished = True
                        break
                else:
                    yield self._event("error", {"message": f"Model call failed: {stream_error}"}, run_id)
                    finished = True
                    break

            if response is None:
                try:
                    response = await self.router.chat_completion_non_stream(
                        messages=self._messages_for_llm(),
                        tools=tool_schemas or None,
                        temperature=0.5,
                        max_tokens=completion_max_tokens,
                        thinking_intensity=ti,
                    )
                except Exception as no_response_fallback_error:
                    yield self._event(
                        "error",
                        {
                            "message": (
                                "Model stream ended without a final response and fallback failed: "
                                f"{no_response_fallback_error}"
                            )
                        },
                        run_id,
                    )
                    finished = True
                    break
                if response is None:
                    yield self._event(
                        "error",
                        {"message": "Model returned no response. Please retry or switch models."},
                        run_id,
                    )
                    finished = True
                    break
            self._update_usage_from_response(response)
            yield self._event("context_usage", self.context_usage(), run_id)

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            is_empty_message = (
                not str(message.get("content") or "").strip()
                and not message.get("tool_calls")
                and not str(message.get("reasoning_content") or "").strip()
            )
            if is_empty_message:
                try:
                    fallback_response = await self.router.chat_completion_non_stream(
                        messages=self._messages_for_llm(),
                        tools=tool_schemas or None,
                        temperature=0.5,
                        max_tokens=completion_max_tokens,
                        thinking_intensity=ti,
                    )
                    fallback_message = fallback_response.get("choices", [{}])[0].get("message", {})
                    fallback_empty = (
                        not str(fallback_message.get("content") or "").strip()
                        and not fallback_message.get("tool_calls")
                        and not str(fallback_message.get("reasoning_content") or "").strip()
                    )
                    if fallback_empty:
                        yield self._event(
                            "error",
                            {"message": "Model returned an empty response. Please retry or switch models."},
                            run_id,
                        )
                        finished = True
                        break
                    response = fallback_response
                    choice = response.get("choices", [{}])[0]
                    message = fallback_message
                    if message.get("reasoning_content"):
                        streamed_reasoning_text += message["reasoning_content"]
                        yield self._event(
                            "reasoning",
                            {"text": message["reasoning_content"], "skill": active_skills[0] if active_skills else None},
                            run_id,
                        )
                    if message.get("content"):
                        streamed_content_text += message["content"]
                        if not buffer_execution_content:
                            streamed_content_visible = True
                            yield self._event(
                                "content",
                                {"text": message["content"], "skill": active_skills[0] if active_skills else None},
                                run_id,
                            )
                except Exception as empty_fallback_error:
                    yield self._event(
                        "error",
                        {"message": f"Model returned an empty response and fallback failed: {empty_fallback_error}"},
                        run_id,
                    )
                    finished = True
                    break

            # Some providers, including Kimi when stream fallback is used, can
            # return a full non-streaming response without token deltas. Make
            # sure the final assistant text is still visible in the UI.
            if message.get("reasoning_content") and not streamed_reasoning_text:
                streamed_reasoning_text = message["reasoning_content"]
                yield self._event(
                    "reasoning",
                    {"text": message["reasoning_content"], "skill": active_skills[0] if active_skills else None},
                    run_id,
                )
            if message.get("content") and not streamed_content_text:
                streamed_content_text = message["content"]
                if not buffer_execution_content:
                    streamed_content_visible = True
                    yield self._event(
                        "content",
                        {"text": message["content"], "skill": active_skills[0] if active_skills else None},
                        run_id,
                    )

            tool_calls = message.get("tool_calls", [])
            assistant_content = message.get("content") or ""
            if (
                buffer_execution_content
                and not tool_calls
                and not stale_build_prompt_guarded
                and self._looks_like_stale_build_prompt(assistant_content or streamed_content_text)
            ):
                stale_build_prompt_guarded = True
                self._append_build_already_clicked_correction(active_turn_id, active_checkpoint_id)
                yield self._event("context_usage", self.context_usage(), run_id)
                continue
            if buffer_execution_content and assistant_content and not streamed_content_visible:
                streamed_content_visible = True
                yield self._event(
                    "content",
                    {"text": assistant_content, "skill": active_skills[0] if active_skills else None},
                    run_id,
                )

            assistant_msg = {
                "role": "assistant",
                "content": assistant_content
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            if message.get("reasoning_content"):
                assistant_msg["reasoning_content"] = message["reasoning_content"]
            self._stamp_message(
                assistant_msg,
                turn_id=active_turn_id,
                checkpoint_id=active_checkpoint_id,
            )
            self.messages.append(assistant_msg)
            yield self._event("context_usage", self.context_usage(), run_id)

            if not tool_calls:
                if (
                    self.chat_mode == "plan"
                    and not self.plan_state.approved
                    and self.plan_state.phase in ("clarifying", "planning")
                ):
                    fallback_questions = self._extract_plan_questions_from_text(
                        str(message.get("content") or streamed_content_text or "")
                    )
                    if fallback_questions:
                        self._apply_plan_questions(fallback_questions)
                        yield self._event("plan_questions", {
                            "questions": [q.model_dump() for q in self.plan_state.questions],
                            "phase": self.plan_state.phase,
                            "pending_clarification": self.plan_state.pending_clarification,
                        }, run_id)
                        yield self._event("plan_status", self._plan_event_payload(), run_id)
                        self._trim_messages()
                        self._save()
                        yield self._event("context_usage", self.context_usage(), run_id)
                        yield self._event("status", {"status": "completed"}, run_id)
                        plan_turn_done = True
                        finished = True
                        break

                # Auto-verification gate: block completion if files were edited without verify
                _proj = ProjectManager.get_current()
                if (
                    _proj
                    and _files_modified
                    and not _verify_called
                    and not _verify_gate_fired
                    and self.chat_mode != "plan"
                ):
                    _verify_gate_fired = True
                    verify_msg = {
                        "role": "user",
                        "source": "internal",
                        "content": (
                            "[VERIFICATION REQUIRED] You modified files this session but have not run "
                            "verify_project. You MUST run verify_project (or the project test/typecheck "
                            "command) before claiming the task is done. Do not say the task is complete "
                            "without showing verification output."
                        ),
                    }
                    self._stamp_message(
                        verify_msg,
                        turn_id=active_turn_id,
                        checkpoint_id=active_checkpoint_id,
                    )
                    self.messages.append(verify_msg)
                    yield self._event("context_usage", self.context_usage(), run_id)
                    continue
                self._trim_messages()
                self._save()
                yield self._event("context_usage", self.context_usage(), run_id)
                yield self._event("status", {"status": "completed"}, run_id)
                finished = True
                break

            tool_results = []
            allowed_names = list_tool_names(self.dynamic_registry)
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments") or "{}"
                tool_id = tc.get("id", "")

                tool_args, parse_error = parse_tool_args(raw_args)
                if parse_error:
                    yield self._event(
                        "tool_call",
                        {"name": tool_name, "args": {}, "result": parse_error, "tool_call_id": tool_id},
                        run_id,
                    )
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": parse_error,
                    })
                    continue

                yield self._event("status", {"status": "executing", "tool": tool_name, "tool_call_id": tool_id}, run_id)

                if self.chat_mode == "plan" and not self.plan_state.approved and not self._is_readonly_plan_tool(tool_name) and tool_name not in self._PLAN_PHASE_TOOLS:
                    blocked = (
                        "[PLAN_GATE] This tool is blocked until the user approves the plan. "
                        "Use read-only discovery tools (file_read, file_list, file_search, git_status, ...) "
                        "or plan_ask_questions / plan_write_draft during planning."
                    )
                    yield self._event(
                        "tool_call",
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "result": blocked,
                            "tool_call_id": tool_id,
                            "duration_ms": 0,
                        },
                        run_id,
                    )
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": blocked,
                    })
                    continue

                # Intent-drift guard: block hallucinated external-resource access
                intent_ok, intent_reason = self._check_tool_intent_consistency(
                    tool_name, tool_args, self._last_user_message
                )
                if not intent_ok:
                    yield self._event(
                        "tool_call",
                        {
                            "name": tool_name,
                            "args": tool_args,
                            "result": intent_reason,
                            "tool_call_id": tool_id,
                            "duration_ms": 0,
                        },
                        run_id,
                    )
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": intent_reason,
                    })
                    continue

                set_browser_session(self.session_id)
                tc_result = await execute_tool(
                    tool_name, tool_args, allowed_names, self.session_id,
                    run_id=run_id,
                    tool_call_id=tool_id,
                    get_tool_fn=lambda name: get_tool(name, self.dynamic_registry),
                )

                # Track file modifications and verification calls for the auto-verification gate
                if tool_name in ("file_patch", "file_write", "file_delete", "coding_file_write") and not tc_result.error:
                    _files_modified = True
                if tool_name == "verify_project":
                    _verify_called = True
                elif tool_name == "shell_execute" and _shell_command_looks_like_verification(
                    str(tool_args.get("command") or "")
                ):
                    _verify_called = True
                    if not tc_result.metadata.get("verification"):
                        _unstructured_verification_seen = True

                if self.plan_state.approved and self.plan_state.phase == "executing":
                    if self._touch_plan_todo_after_tool(tool_name, tc_result.result_text, tc_result.error or ""):
                        yield self._event(
                            "todo_update",
                            {"todos": [t.model_dump() for t in self.plan_state.todos]},
                            run_id,
                        )

                if tc_result.base64_image:
                    yield self._event("image", {"base64": tc_result.base64_image, "source": tool_name, "tool_call_id": tool_id}, run_id)

                if tc_result.metadata.get("file_edit"):
                    file_edit = dict(tc_result.metadata["file_edit"])
                    file_edit.setdefault("tool_call_id", tool_id)
                    yield self._event("file_edit", file_edit, run_id)

                if tc_result.metadata.get("skill_draft"):
                    draft = dict(tc_result.metadata["skill_draft"])
                    draft.setdefault("tool_call_id", tool_id)
                    yield self._event("skill_draft_ready", draft, run_id)

                for decision in tc_result.metadata.get("guardrail_decisions", []):
                    yield self._event("guardrail_decision", decision, run_id)
                    if decision.get("requires_approval"):
                        yield self._event("approval_required", decision, run_id)

                if tc_result.metadata.get("verification"):
                    _latest_verification = tc_result.metadata["verification"]
                    yield self._event("verification_result", _latest_verification, run_id)

                if tc_result.metadata.get("review"):
                    _latest_review = tc_result.metadata["review"]
                    for finding in _latest_review.get("findings", []):
                        yield self._event("review_finding", finding, run_id)

                recorder = get_recorder(self.session_id)
                if recorder and recorder.is_recording() and not tc_result.error:
                    recorder.record_step(tool_name, tool_args)

                # ── plan tool result processing ──
                plan_action = tc_result.metadata.get("plan_action")
                if plan_action == "questions_submitted":
                    assistant_msg["content"] = ""
                    self._apply_plan_questions(tc_result.metadata.get("questions") or [])
                    yield self._event("plan_questions", {
                        "questions": [q.model_dump() for q in self.plan_state.questions],
                        "phase": self.plan_state.phase,
                        "pending_clarification": self.plan_state.pending_clarification,
                    }, run_id)
                    yield self._event("plan_status", self._plan_event_payload(), run_id)
                    plan_turn_done = True

                elif plan_action == "draft_submitted":
                    assistant_msg["content"] = ""
                    self._apply_plan_draft(tc_result.metadata.get("payload") or {})
                    yield self._event("plan_draft", {
                        "goal": self.plan_state.goal,
                        "draft": self.plan_state.draft,
                        "structured_plan": self.plan_state.structured_plan.model_dump() if self.plan_state.structured_plan else None,
                        "todos": [t.model_dump() for t in self.plan_state.todos],
                        "phase": self.plan_state.phase,
                        "pending_clarification": self.plan_state.pending_clarification,
                    }, run_id)
                    if self.plan_state.plan_file_path:
                        yield self._event("plan_file_ready", {
                            "plan_file_path": self.plan_state.plan_file_path,
                            "markdown": self.plan_state.draft,
                        }, run_id)
                    yield self._event("todo_update", {
                        "todos": [t.model_dump() for t in self.plan_state.todos],
                    }, run_id)
                    yield self._event("plan_status", self._plan_event_payload(), run_id)
                    plan_turn_done = True

                elif plan_action == "todos_updated":
                    # Model-driven todo progression during BUILD execution.
                    # Apply the explicit status changes, auto-advance the next
                    # pending todo, and emit todo_update RIGHT NOW so the plan
                    # card ticks item-by-item (do not batch / wait for turn end).
                    self._apply_todo_updates(tc_result.metadata.get("payload") or {})
                    self._auto_advance_pending_todos()
                    self._save()
                    yield self._event("todo_update", {
                        "todos": [t.model_dump() for t in self.plan_state.todos],
                    }, run_id)
                    if (
                        self.plan_state.phase == "executing"
                        and self.plan_state.todos
                        and all(
                            t.status in ("completed", "cancelled")
                            for t in self.plan_state.todos
                        )
                    ):
                        self.plan_state.transition_to("completed")
                        self._save()
                        yield self._event("plan_status", self._plan_event_payload(), run_id)
                    # NOTE: deliberately NOT setting plan_turn_done — execution
                    # must continue to the next todo within the same run.

                yield self._event(
                    "tool_call",
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "result": tc_result.result_text,
                        "tool_call_id": tool_id,
                        "duration_ms": tc_result.duration_ms,
                    },
                    run_id,
                )

                for collaboration_event in tc_result.metadata.get("collaboration_events", []) or []:
                    if not isinstance(collaboration_event, dict):
                        continue
                    event_data = dict(collaboration_event.get("data") or {})
                    collab_run_id = collaboration_event.get("run_id") or event_data.get("run_id") or ""
                    collab_task_id = collaboration_event.get("task_id") or event_data.get("task_id") or ""
                    if collab_run_id:
                        event_data.setdefault("run_id", collab_run_id)
                        event_data.setdefault("collaboration_run_id", collab_run_id)
                    if collab_task_id:
                        event_data.setdefault("task_id", collab_task_id)
                        event_data.setdefault("collaboration_task_id", collab_task_id)
                    event_data.setdefault("timestamp", collaboration_event.get("timestamp") or time.time())
                    yield self._event(
                        collaboration_event.get("type", "collaboration_task_update"),
                        event_data,
                    )

                result_text = tc_result.result_text
                max_tool_result_len = 8000
                if len(result_text) > max_tool_result_len:
                    result_text = result_text[:max_tool_result_len] + f"\n\n[输出过长，已截断。原长度 {len(tc_result.result_text)} 字符]"
                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result_text,
                })

            for result_msg in tool_results:
                self._stamp_message(
                    result_msg,
                    turn_id=active_turn_id,
                    checkpoint_id=active_checkpoint_id,
                )
            self.messages.extend(tool_results)
            self._trim_messages()
            self._save()
            yield self._event("context_usage", self.context_usage(), run_id)
            yield self._event("status", {"status": "thinking"}, run_id)

            if plan_turn_done:
                # Plan tool was executed — stop here; user review needed.
                finished = True
                break

        # ── plan mode: graceful end-of-turn when no plan tool was called ──
        if self.chat_mode == "plan" and not plan_turn_done and not self.plan_state.approved \
                and self.plan_state.phase in ("clarifying", "planning"):
            # The LLM's text reply (clarifying question / research summary) already
            # streamed to the user. End the turn cleanly — keep phase so the user can
            # answer and continue the conversation. Never synthesize a template plan.
            msg = "max_iterations" if self.iteration >= self.max_iterations else ""
            yield self._event("plan_status", {**self._plan_event_payload(), "message": msg or "clarifying"}, run_id)

        if not finished and self.iteration >= self.max_iterations:
            yield self._event("status", {"status": "max_iterations_reached"}, run_id)
        completion_status = "cancelled" if self._cancelled else (
            "max_iterations_reached" if not finished and self.iteration >= self.max_iterations else "completed"
        )
        completion_summary = f"Run {completion_status} after {self.iteration} iteration(s)."
        completion_quality = _completion_quality_payload(
            files_modified=_files_modified,
            latest_verification=_latest_verification,
            latest_review=_latest_review,
            unstructured_verification_seen=_unstructured_verification_seen,
        )
        if self.plan_state.phase == "executing" and completion_status == "completed":
            # The run finished naturally. The plan card spinner is bound to
            # phase == "executing", so phase MUST leave "executing" here or it
            # spins forever. User-chosen behavior: mark every non-blocked /
            # non-cancelled todo completed and transition to a terminal phase;
            # blocked todos stay visible as blocked.
            for t in self.plan_state.todos:
                if t.status in ("in_progress", "pending"):
                    t.status = "completed"
            self.plan_state.transition_to("completed")
            yield self._event("todo_update", {"todos": [t.model_dump() for t in self.plan_state.todos]}, run_id)
            yield self._event("plan_status", self._plan_event_payload(), run_id)
        yield self._event("run_completed", {
            "status": completion_status,
            "summary": completion_summary,
            **completion_quality,
        }, run_id)
        close_coding_run(completion_status, completion_summary, completion_quality)
        self._save()

    def _touch_plan_todo_after_tool(self, tool_name: str, result_text: str = "", tool_error: str = "") -> bool:
        """Best-effort todo progression after worker dispatch tools (plan execution). Returns True if todos changed."""
        if not self.plan_state.approved or self.plan_state.phase != "executing" or not self.plan_state.todos:
            return False
        if tool_name not in ("dispatch_worker", "dispatch_parallel"):
            return False
        todos = self.plan_state.todos
        changed = False
        # Only advance in_progress → completed when worker signals success, or no acceptance signal at all
        dispatch_failed = bool(tool_error) or result_text.startswith("[ERROR]")
        acceptance_fail = dispatch_failed or "ACCEPTANCE: FAIL" in result_text
        acceptance_pass = "ACCEPTANCE: PASS" in result_text
        for t in todos:
            if t.status == "in_progress":
                if acceptance_fail:
                    t.status = "blocked"
                else:
                    # Mark completed if ACCEPTANCE: PASS or no acceptance token (legacy workers)
                    t.status = "completed"
                changed = True
                break
        if not acceptance_fail:
            if self._auto_advance_pending_todos():
                changed = True
        return changed

    def _auto_advance_pending_todos(self) -> bool:
        """Promote the next dependency-ready pending todo to in_progress when
        nothing is currently running. Returns True if a todo changed.

        Shared by the worker-dispatch fallback (_touch_plan_todo_after_tool)
        and the explicit plan_update_todos path so direct execution also keeps
        a single todo active at a time.
        """
        todos = self.plan_state.todos
        if not todos:
            return False
        if any(t.status == "in_progress" for t in todos):
            return False
        for t in todos:
            if t.status != "pending":
                continue
            deps = t.depends_on or []
            if not deps or all(
                (self._todo_by_id(d) and self._todo_by_id(d).status == "completed") for d in deps
            ):
                t.status = "in_progress"
                return True
        return False

    def _apply_todo_updates(self, payload: Dict[str, Any]) -> bool:
        """Apply explicit {id, status} changes from the plan_update_todos tool.

        Returns True if any todo status actually changed. Unknown ids and
        invalid statuses are skipped (the tool already validated shape).
        """
        updates = payload.get("updates") or []
        if not isinstance(updates, list) or not self.plan_state.todos:
            return False
        valid = {"pending", "in_progress", "completed", "blocked", "cancelled"}
        changed = False
        for u in updates:
            if not isinstance(u, dict):
                continue
            todo = self._todo_by_id(str(u.get("id", "")))
            status = u.get("status")
            if todo is None or status not in valid:
                continue
            if todo.status != status:
                todo.status = status
                changed = True
        return changed

    def _todo_by_id(self, todo_id: str) -> Optional[PlanTodo]:
        for t in self.plan_state.todos:
            if t.id == todo_id:
                return t
        return None

    _CODE_INTENT_PATTERNS = [
        # Chinese patterns
        r"(写|帮我写|编写|实现|开发|新建|创建)\s*(一个|个|代码|程序|脚本|功能|模块|组件|页面|API|接口)",
        r"(修复|修|fix|debug|调试)\s*(这个|那个|bug|问题|错误|报错|异常)",
        r"(重构|refactor|重写|rewrite|优化|optimize)\s*(这个|代码|函数|方法|模块)",
        r"(添加|增加|新增|add)\s*(功能|feature|测试|test|单元测试)",
        r"(修改|改|modify|change|update)\s*(代码|文件|配置|逻辑|实现)",
        r"(帮我|请|能不能|可以|能否).*(写|改|修|实现|开发|重构|优化|添加).*(代码|功能|文件|程序)",
        r"(run|运行)\s*(test|测试|pytest|vitest)",
        r"(git|Git)\s*(commit|push|merge|rebase|branch)",
        r"(review|审查|检查)\s*(代码|code|PR|pull request)",
        # English patterns
        r"(write|create|build|implement|develop|code|make)\s+(a|an|the|some)?\s*(code|function|module|component|feature|script|page|API|endpoint|service|class|test)",
        r"(fix|debug|resolve|patch|repair)\s+(the|a|an|this|that)?\s*(bug|issue|error|problem|exception|crash)",
        r"(refactor|rewrite|optimize|improve|clean\s*up)\s+(the|this|code|function|method|module|class)",
        r"(add|implement|create)\s+(a|an|the|some)?\s*(feature|test|unit\s*test|integration\s*test|endpoint|API)",
        r"(modify|change|update|edit|alter)\s+(the|this|code|file|config|logic|implementation)",
        r"(can|could|would)\s+you\s+(write|fix|create|build|implement|refactor|change|update|add)",
        r"^(fix|write|create|build|add|update|refactor|implement)\b",
    ]

    @classmethod
    def _detect_code_intent(cls, user_input: str) -> bool:
        """Detect if a user message expresses code development intent."""
        import re
        user_lower = user_input.lower()
        for pattern in cls._CODE_INTENT_PATTERNS:
            if re.search(pattern, user_input) or re.search(pattern, user_lower):
                return True
        return False

    def _should_screenshot(self) -> bool:
        desktop_tools = ["mouse_click", "mouse_move", "type_text", "press_key", "scroll", "app_click"]
        if self.messages:
            last = self.messages[-1]
            if last.get("role") == "assistant" and "tool_calls" in last:
                for tc in last["tool_calls"]:
                    if tc.get("function", {}).get("name") in desktop_tools:
                        return True
        return self.iteration % 5 == 0

    async def compact_context(self, focus: str = "", force: bool = False) -> Optional[Dict[str, Any]]:
        """Compress older conversation turns into the session summary.

        The summary is injected into the rebuilt system prompt instead of being
        stored as a second system message. That keeps provider-specific system
        handling predictable while preserving recent turns verbatim.
        """
        COMPACTION_THRESHOLD = 15
        RECENT_USER_TURNS = 3

        self._ensure_message_metadata()
        before_count = len([m for m in self.messages if m.get("role") != "system"])
        current_usage = self.context_usage()
        if not force and before_count < COMPACTION_THRESHOLD and current_usage["used_percent"] < 70:
            return {
                "skipped": True,
                "reason": "Current context is still healthy; no compaction is needed yet.",
                "message": "当前无需压缩，Context 仍然充足。",
                "summary": self.compaction_summary,
                "before_message_count": before_count,
                "after_message_count": before_count,
                "context_usage": current_usage,
            }

        history = [m for m in self.messages if m.get("role") != "system"]
        real_user_checkpoint_ids: list[str] = []
        for msg in history:
            if msg.get("role") == "user" and msg.get("source") != "internal":
                checkpoint_id = msg.get("checkpoint_id")
                if checkpoint_id and checkpoint_id not in real_user_checkpoint_ids:
                    real_user_checkpoint_ids.append(str(checkpoint_id))
        recent_checkpoint_ids = set(real_user_checkpoint_ids[-RECENT_USER_TURNS:])
        if not recent_checkpoint_ids and history:
            recent_checkpoint_ids = {str(history[-1].get("checkpoint_id") or "")}

        recent: list[dict[str, Any]] = []
        to_summarize: list[dict[str, Any]] = []
        for msg in history:
            if msg.get("checkpoint_id") in recent_checkpoint_ids:
                recent.append(copy.deepcopy(msg))
            else:
                to_summarize.append(msg)

        if len(to_summarize) < 2:
            return {
                "skipped": True,
                "reason": "There are not enough older turns to compact safely.",
                "message": "可压缩的旧对话不足，已保持当前上下文不变。",
                "summary": self.compaction_summary,
                "before_message_count": before_count,
                "after_message_count": before_count,
                "context_usage": current_usage,
            }

        conv_lines: list[str] = []
        for msg in to_summarize:
            role = msg.get("role", "?")
            name = msg.get("name") or ""
            content = _text_from_content(msg.get("content", "")).strip()
            if msg.get("tool_calls"):
                tool_names = [
                    ((tc.get("function") or {}).get("name") or "tool")
                    for tc in msg.get("tool_calls", [])
                    if isinstance(tc, dict)
                ]
                content = (content + "\n" if content else "") + f"[tool_calls: {', '.join(tool_names)}]"
            conv_lines.append(f"[{role}{':' + name if name else ''}] {content[:1200]}")
        conv_text = "\n\n".join(conv_lines)

        prompt_parts = [
            "Summarize the older part of this Desktop Agent session for future continuation.",
            "Preserve durable facts, user preferences, decisions, open tasks, plan/todo state, files touched, tool results, blockers, and warnings.",
            "Do not include filler or transcript-like detail. Use the same primary language as the conversation.",
        ]
        if focus:
            prompt_parts.append(f"User focus for this compaction: {focus}")
        if self.compaction_summary:
            prompt_parts.append(f"Previous compacted summary to merge:\n{self.compaction_summary[:4000]}")
        if self.plan_state.phase != "idle" or self.plan_state.goal:
            prompt_parts.append(
                "Current plan state:\n"
                + json.dumps(self.plan_state.model_dump(), ensure_ascii=False)[:4000]
            )
        prompt_parts.append(f"Conversation to compact:\n{conv_text[:14000]}")

        summary_messages = [
            {"role": "system", "content": "\n\n".join(prompt_parts)},
            {"role": "user", "content": "Create the compacted continuation summary now."},
        ]

        try:
            response = await self.router.chat_completion_non_stream(
                messages=summary_messages,
                temperature=0.2,
                max_tokens=1600,
            )
            self._update_usage_from_response(response)
            summary = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not summary or len(summary) < 10:
                return None
        except Exception as e:
            logger.warning("Context compaction failed: %s", e)
            return None

        self.compaction_summary = summary[:6000]
        self.messages = recent
        self._refresh_system_prompt()
        self._ensure_message_metadata()
        after_count = len([m for m in self.messages if m.get("role") != "system"])
        usage = self.context_usage()
        logger.info("Context compacted: %d -> %d messages", before_count, after_count)
        self._save()
        return {
            "skipped": False,
            "summary": self.compaction_summary,
            "new_summary": summary,
            "before_message_count": before_count,
            "after_message_count": after_count,
            "context_usage": usage,
        }

    def cancel(self):
        self._cancelled = True
        cancel_workers_for_session(self.session_id)
        for worker in self._active_workers:
            try:
                worker.cancel()
            except Exception:
                pass

    def retry_last(self) -> bool:
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.get("role") == "assistant":
                self.messages = self.messages[:i]
                self.iteration = 0
                self._cancelled = False
                active_user = next((m for m in reversed(self.messages) if m.get("role") == "user"), None)
                if active_user:
                    self._last_user_message = _text_from_content(active_user.get("content", ""))
                self._refresh_system_prompt()
                self._save()
                return True
        return False

    def reset(self):
        self.messages = []
        self.iteration = 0
        self._cancelled = False
        self.compaction_summary = ""
        self._last_usage = {}
        self._last_context_usage = {}
        self.chat_mode = "agent"
        self.thinking_intensity = getattr(
            load_config().settings, "thinking_intensity_default", "medium"
        ) or "medium"
        if self.thinking_intensity not in ("low", "medium", "high"):
            self.thinking_intensity = "medium"
        self._agent_thinking[self._agent_type] = self.thinking_intensity
        self.plan_state = PlanState()
        self._plan_exec_hint_sent = False
        self._repo_map_cache = None
        self._setup_system_prompt()
        self._save()

    def switch_agent(self, agent_type: str):
        """Switch the active agent type, model, thinking intensity, and refresh the system prompt."""
        if agent_type not in ("personal", "coding"):
            raise ValueError(f"Unknown agent_type: {agent_type}")
        if agent_type != self._agent_type and _session_has_history(self):
            raise ValueError(
                "Cannot switch a non-empty session between agent identities. "
                "Resolve or create a session for the target agent instead."
            )

        AgentManager.switch_agent(self, agent_type)

        # Switch to the agent's configured model
        effective = self._resolve_agent_model()
        if effective != self.model_id:
            self.model_id = effective
            try:
                self.router = ModelRouter(effective)
            except ValueError:
                pass  # Keep existing router if new model is unrecognised

        # Update thinking intensity for the new agent, preferring any UI override
        # already stored in this session.
        ti = self._agent_thinking.get(agent_type) or get_thinking_intensity_for_agent(agent_type)
        if ti in ("low", "medium", "high"):
            self.thinking_intensity = ti
            self._agent_thinking[agent_type] = ti

        self._save()

    def switch_role(self, role_id: str):
        """Backward-compatible alias for switch_agent."""
        agent_type = AgentManager.get_agent_type_for_role(role_id)
        if agent_type != self._agent_type and _session_has_history(self):
            raise ValueError(
                "Cannot switch a non-empty session between agent identities. "
                "Resolve or create a session for the target agent instead."
            )
        self.role_id = role_id
        self._agent_type = agent_type
        self._refresh_system_prompt()
        self._save()

    def refresh_mcp_tools(self):
        """从 MCP Manager 刷新动态工具到当前会话。"""
        from app.mcp.manager import get_mcp_manager
        from app.tools.mcp_tool import McpToolProxy
        manager = get_mcp_manager()
        self.dynamic_registry.clear()
        for server_status in manager.list_servers():
            if server_status.connected:
                for t in server_status.tools:
                    proxy = McpToolProxy(
                        server_id=server_status.id,
                        tool_name=t.name,
                        description=t.description,
                        parameters=t.parameters,
                    )
                    self.dynamic_registry.register(proxy)
        self._refresh_system_prompt()
        self._save()

    def _save(self):
        path = SESSIONS_DIR / f"{self.session_id}.json"
        self._ensure_message_metadata()
        # Extract title from first user message
        title = ""
        for m in self.messages:
            if m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
                title = m["content"].strip()[:80]
                break
        if not title and self.plan_state.goal:
            title = self.plan_state.goal[:80]
        # Get current project path
        project_path = None
        try:
            proj = ProjectManager.get_current()
            if proj:
                project_path = proj.get("path")
        except Exception:
            pass

        data = {
            "session_id": self.session_id,
            "model_id": self.model_id,
            "role_id": self.role_id,
            "agent_type": self._agent_type,
            "agent_models": self._agent_models,
            "agent_thinking": self._agent_thinking,
            "messages": self.messages,
            "iteration": self.iteration,
            "chat_mode": self.chat_mode,
            "thinking_intensity": self.thinking_intensity,
            "plan_state": self.plan_state.model_dump(),
            "compaction_summary": self.compaction_summary,
            "last_usage": self._last_usage,
            "last_context_usage": self._last_context_usage,
            "title": title,
            "project_path": project_path,
        }
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass

    @classmethod
    def load(cls, session_id: str) -> Optional["AgentSession"]:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # agent_type: prefer stored value, else migrate from role_id
            stored_agent_type = data.get("agent_type")
            stored_role_id = data.get("role_id", "desktop-agent")
            if not stored_agent_type:
                stored_agent_type = AgentManager.get_agent_type_for_role(stored_role_id)

            session = cls(
                model_id=data.get("model_id", "kimi-for-coding"),
                session_id=session_id,
                role_id=stored_role_id,
                agent_type=stored_agent_type,
            )
            session.messages = data.get("messages", [])
            session.iteration = 0
            session.compaction_summary = str(data.get("compaction_summary") or "")
            last_usage = data.get("last_usage")
            session._last_usage = last_usage if isinstance(last_usage, dict) else {}
            last_context_usage = data.get("last_context_usage")
            session._last_context_usage = last_context_usage if isinstance(last_context_usage, dict) else {}

            # Restore per-agent model and thinking intensity from persisted data
            stored_agent_models = data.get("agent_models")
            if isinstance(stored_agent_models, dict):
                for at in ("personal", "coding"):
                    if at in stored_agent_models:
                        session._agent_models[at] = stored_agent_models[at]
            stored_agent_thinking = data.get("agent_thinking")
            if isinstance(stored_agent_thinking, dict):
                for at in ("personal", "coding"):
                    if stored_agent_thinking.get(at) in ("low", "medium", "high"):
                        session._agent_thinking[at] = stored_agent_thinking[at]

            cm = data.get("chat_mode", "agent")
            session.chat_mode = cm if cm in ("agent", "plan") else "agent"
            ti = data.get("thinking_intensity", "medium")
            session.thinking_intensity = ti if ti in ("low", "medium", "high") else "medium"
            session._agent_thinking[session._agent_type] = session.thinking_intensity
            ps = data.get("plan_state")
            if isinstance(ps, dict):
                try:
                    session.plan_state = PlanState.model_validate(ps)
                except Exception:
                    session.plan_state = PlanState()
            session._ensure_message_metadata()
            session._trim_messages()
            session._refresh_system_prompt()
            session.refresh_mcp_tools()
            return session
        except (OSError, json.JSONDecodeError):
            return None

    def get_history_events(self) -> List[Dict[str, Any]]:
        events = []
        for msg in self.messages:
            role = msg.get("role")
            if role == "user":
                continue
            if role == "assistant":
                if msg.get("reasoning_content"):
                    events.append({"type": "reasoning", "data": {"text": msg["reasoning_content"]}})
                if msg.get("content"):
                    events.append({"type": "content", "data": {"text": msg["content"]}})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except (TypeError, ValueError, json.JSONDecodeError):
                            args = {}
                        events.append({
                            "type": "tool_call",
                            "data": {
                                "name": func.get("name", ""),
                                "args": args,
                                "result": "[executed]",
                            }
                        })
            elif role == "tool":
                events.append({
                    "type": "tool_call",
                    "data": {
                        "name": msg.get("name", ""),
                        "args": {},
                        "result": msg.get("content", ""),
                    }
                })
        return events

    def to_snapshot(self) -> Dict[str, Any]:
        context_usage = self.context_usage()
        return {
            "session_id": self.session_id,
            "model_id": self.model_id,
            "role_id": self.role_id,
            "agent_type": self._agent_type,
            "agent_models": self._agent_models,
            "agent_thinking": self._agent_thinking,
            "messages": self.messages,
            "iteration": self.iteration,
            "chat_mode": self.chat_mode,
            "thinking_intensity": self.thinking_intensity,
            "plan_state": self.plan_state.model_dump(),
            "compaction_summary": self.compaction_summary,
            "context_usage": context_usage,
            "checkpoints": self.build_checkpoints(),
        }


MAX_LIVE_SESSIONS = 32

# LRU of in-memory sessions. Eviction does NOT delete the on-disk JSON; the
# next access falls through to AgentSession.load and rehydrates state.
_sessions: "OrderedDict[str, AgentSession]" = OrderedDict()


def _touch(session_id: str) -> None:
    _sessions.move_to_end(session_id)


def _evict_if_needed() -> None:
    while len(_sessions) > MAX_LIVE_SESSIONS:
        _sessions.popitem(last=False)


def get_or_create_session(session_id: str, model_id: str, role_id: str | None = None, agent_type: str | None = None) -> AgentSession:
    existing = _sessions.get(session_id)
    provided_role_id = role_id
    role_id = role_id or (AgentManager.get_default_role(agent_type) if agent_type else "desktop-agent")
    resolved_agent_type = agent_type or AgentManager.get_agent_type_for_role(role_id)
    loaded_from_disk = False
    if existing is None:
        loaded = AgentSession.load(session_id)
        if loaded:
            _sessions[session_id] = loaded
            loaded_from_disk = True
        else:
            _sessions[session_id] = AgentSession(model_id=model_id, session_id=session_id, role_id=role_id, agent_type=resolved_agent_type)
            _sessions[session_id].refresh_mcp_tools()

    session = _sessions[session_id]
    changed = False
    if agent_type and session.agent_type != resolved_agent_type:
        if _session_has_history(session):
            raise ValueError(
                f"Session {session_id} already belongs to {session.agent_type}; "
                f"cannot reuse it as {resolved_agent_type}. Use /api/sessions/resolve for the target agent."
            )
        session.switch_agent(resolved_agent_type)
        changed = True
    elif provided_role_id and role_id != session.role_id:
        target_agent_type = AgentManager.get_agent_type_for_role(role_id)
        if target_agent_type != session.agent_type and _session_has_history(session):
            raise ValueError(
                f"Session {session_id} already belongs to {session.agent_type}; "
                f"cannot reuse it as {target_agent_type}. Use /api/sessions/resolve for the target agent."
            )
        session.switch_role(role_id)
        changed = True

    should_keep_loaded_model = loaded_from_disk and agent_type is None and provided_role_id is None
    if model_id and session.model_id != model_id and not should_keep_loaded_model:
        session.model_id = model_id
        session.router = ModelRouter(model_id)
        session._agent_models[session.agent_type] = model_id
        session._refresh_system_prompt()
        changed = True

    if changed:
        session._save()

    _touch(session_id)
    _evict_if_needed()
    return _sessions[session_id]


def _new_coding_session_id() -> str:
    while True:
        session_id = f"session_coding_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        if session_id not in _sessions and not (SESSIONS_DIR / f"{session_id}.json").exists():
            return session_id


def _new_session_summary(
    session: AgentSession,
    *,
    created: bool,
    is_primary: bool,
) -> Dict[str, Any]:
    try:
        project = ProjectManager.get_current()
        project_path = project.get("path") if project else None
    except Exception:
        project_path = None
    return {
        "session_id": session.session_id,
        "agent_type": session.agent_type,
        "role_id": session.role_id,
        "model_id": session.model_id,
        "title": _session_title_from_messages(session.messages, session.plan_state),
        "project_path": project_path,
        "created": created,
        "is_primary": is_primary,
    }


def _newest_matching_session_id(agent_type: str, project_path: str | None = None) -> str | None:
    records = list_session_records(project_path=project_path or "", agent_type=agent_type)
    return records[0]["id"] if records else None


def resolve_agent_session(agent_type: str, policy: str, project_path: str | None = None) -> Dict[str, Any]:
    """Resolve the session identity that should back an agent navigation action."""
    if agent_type not in ("personal", "coding"):
        raise ValueError(f"Unknown agent_type: {agent_type}")
    if policy not in ("canonical", "last_or_create", "new"):
        raise ValueError(f"Unknown session resolve policy: {policy}")

    registry = _load_session_registry()
    role_id = AgentManager.get_default_role(agent_type)
    model_id = get_model_for_agent(agent_type)

    if agent_type == "personal":
        personal = registry.setdefault("personal", {})
        session_id = personal.get("primary_session_id")
        if not session_id or not _session_record_matches(session_id, agent_type="personal"):
            session_id = _newest_matching_session_id("personal") or "session_personal_main"

        created = session_id not in _sessions and not (SESSIONS_DIR / f"{session_id}.json").exists()
        session = get_or_create_session(session_id, model_id, role_id=role_id, agent_type="personal")
        if created or not (SESSIONS_DIR / f"{session_id}.json").exists():
            session._save()

        personal["primary_session_id"] = session.session_id
        _save_session_registry(registry)
        return _new_session_summary(session, created=created, is_primary=True)

    coding = registry.setdefault("coding", {})
    last_by_project = coding.setdefault("last_session_by_project", {})
    project_key = _normalize_project_key(project_path)

    session_id = ""
    if policy != "new":
        candidate = last_by_project.get(project_key)
        if candidate and _session_record_matches(candidate, agent_type="coding", project_path=project_path):
            session_id = candidate
        else:
            session_id = _newest_matching_session_id("coding", project_path)

    if not session_id:
        session_id = _new_coding_session_id()

    created = session_id not in _sessions and not (SESSIONS_DIR / f"{session_id}.json").exists()
    session = get_or_create_session(session_id, model_id, role_id=role_id, agent_type="coding")
    if created or not (SESSIONS_DIR / f"{session_id}.json").exists():
        session._save()

    last_by_project[project_key] = session.session_id
    _save_session_registry(registry)
    return _new_session_summary(session, created=created, is_primary=False)


def refresh_all_sessions_mcp_tools():
    """通知所有活跃会话刷新 MCP 工具。"""
    for session in _sessions.values():
        try:
            session.refresh_mcp_tools()
        except Exception:
            pass


def clear_session(session_id: str):
    if session_id in _sessions:
        _sessions[session_id].reset()
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
