import json
import logging
import ntpath
import os
import time
import uuid
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
from app.models import ModelRouter
from app.memory import build_memory_prompt
from app.project_manager import ProjectManager
from app.project_rules import build_rules_prompt
from app.roles import RoleManager  # deprecated — kept for backward compat
from app.agents.manager import AgentManager
from app.runtime_paths import runtime_dir, backend_root
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

# Internal: resume agent loop after user clicks Build (WebSocket `build_plan`).
PLAN_CONTINUE_MARKER = "__plan_continue__"

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
        self.dynamic_registry = DynamicToolRegistry()
        self.chat_mode = "agent"
        self.thinking_intensity = self._agent_thinking.get(self._agent_type, "medium")
        self.plan_state = PlanState()
        self._plan_exec_hint_sent = False
        self._repo_map_cache: Optional[Dict[str, Any]] = None
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
                self._last_user_message, self.role_id, project is not None
            )
            if matched_skills:
                skill_prompt = SkillManager.build_skill_prompt(matched_skills)
                if skill_prompt:
                    system_msg += f"\n\n## Active Skills\n{skill_prompt}\n"

        # Auto-inject RAG context if knowledge base has indexed documents.
        # Cache results per (user_message, doc_count) to avoid redundant embedding
        # searches across _refresh_system_prompt calls (retry, MCP refresh, etc.).
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
                    # Build a cache key from the user message + doc count hint
                    doc_key = f"{self._last_user_message}::{len(docs)}"
                    if doc_key != self._rag_cache_key:
                        results = rag.search(self._last_user_message, top_k=3)
                        relevant = [r for r in results if r.score >= 0.3]
                        if relevant:
                            rag_ctx = "\n\n## Relevant Knowledge Base Context\n"
                            for r in relevant:
                                rag_ctx += f"\n### {r.source_path} (score: {r.score:.2f})\n{r.content[:800]}\n"
                            self._rag_cache_text = rag_ctx
                        else:
                            self._rag_cache_text = ""
                        self._rag_cache_key = doc_key
                    if self._rag_cache_text:
                        system_msg += self._rag_cache_text
        except Exception as e:
            logger.warning("RAG auto-retrieval failed: %s", e)

        # Inject team shared context
        if self.team_id:
            from .teams import build_team_context_prompt
            team_ctx = build_team_context_prompt(self.team_id, self.team_name or "Team")
            if team_ctx:
                system_msg += team_ctx

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
        self.chat_mode = mode
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
        if not self.plan_state.structured_plan:
            return ""
        plan = self.plan_state.structured_plan
        lines = [
            f"Goal: {plan.goal or user_input.strip()[:800]}",
            "",
            "Structured steps:",
        ]
        for t in plan.todos:
            deps = f" (depends_on: {', '.join(t.depends_on)})" if t.depends_on else ""
            grp = f" [parallel_group: {t.parallel_group}]" if t.parallel_group else ""
            lines.append(f"- [{t.id}] {t.title}{deps}{grp}")
        if plan.acceptance_criteria:
            lines.extend(["", "Acceptance criteria:"])
            for item in plan.acceptance_criteria:
                lines.append(f"- {item}")
        return "\n".join(lines)

    def _inject_plan_execution_hint(self) -> None:
        if self._plan_exec_hint_sent or not self.plan_state.approved:
            return
        cfg = load_config().settings
        mode = getattr(cfg, "collaboration_mode", "serial") or "serial"
        lines = [
            "[Plan execution — follow the approved plan below]",
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
        lines.append("## Execution Rules")
        lines.append("- Process todos in dependency order. Mark as in_progress before starting, completed when done.")
        lines.append("- If blocked, mark the todo as blocked and explain why.")
        lines.append("- After implementation, run verify_project and git_diff for review.")
        lines.append("- When dispatching a worker for a todo, include the todo's acceptance_criteria in the task description.")
        lines.append("- Ask each worker to end its response with exactly: ACCEPTANCE: PASS or ACCEPTANCE: FAIL")
        lines.append("- Only mark a todo as completed if the worker reports ACCEPTANCE: PASS.")
        self.messages.append({"role": "system", "content": "\n".join(lines)})
        self._plan_exec_hint_sent = True

    def _start_plan_execution(self) -> None:
        self.plan_state.transition_to("executing")
        self._plan_exec_hint_sent = False
        if self.plan_state.todos:
            first = self.plan_state.todos[0]
            if first.status == "pending":
                first.status = "in_progress"

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
        valid_phase = self.plan_state.phase in ("awaiting_approval", "approved_waiting_build")
        if not valid_phase:
            return False
        self.plan_state.approved = True
        self._start_plan_execution()
        # Auto-switch to agent mode so subsequent messages don't re-enter plan flow.
        self.chat_mode = "agent"
        self._save()
        return True

    def update_plan_decision(self, question_id: str, selected: List[str]) -> None:
        self.plan_state.decisions[question_id] = list(selected)
        all_answered = all(q.id in self.plan_state.decisions for q in self.plan_state.questions)
        if not all_answered or self.plan_state.phase != "awaiting_decision":
            self._save()
            return

        # Feed decisions back to the LLM so it can synthesize a researched plan.
        lines = ["[User answered the plan clarification questions:]"]
        for q in self.plan_state.questions:
            picks = self.plan_state.decisions.get(q.id, [])
            label_by_id = {o.id: o.label for o in q.options}
            labels = [label_by_id.get(p, p) for p in picks]
            if labels:
                lines.append(f"- {q.prompt} => {', '.join(labels)}")
        lines.append("")
        lines.append("Please synthesize these decisions with your research and call plan_write_draft.")
        self.messages.append({"role": "user", "content": "\n".join(lines)})
        self.plan_state.pending_clarification = False
        self.plan_state.questions = []
        self.plan_state.decisions = {}
        self.plan_state.transition_to("planning")
        self._save()

    # ── LLM-driven plan tool application ──

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
        self.plan_state.questions = qs
        self.plan_state.pending_clarification = True
        self.plan_state.transition_to("awaiting_decision")
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
        draft = PlanDraft(
            goal=payload.get("goal", ""),
            assumptions=payload.get("assumptions", []) or [],
            steps=steps,
            todos=todos,
            risks=payload.get("risks", []) or [],
            acceptance_criteria=payload.get("verification", []) or [],
        )

        # Build draft text from markdown body
        draft_text = payload.get("markdown_body", "")
        if not draft_text:
            draft_text = self._build_plan_draft_text(payload.get("goal", ""))

        # Persist plan file
        research_notes = payload.get("research_notes", "")
        self.plan_state.research_notes = research_notes
        try:
            path = write_plan_file(self.session_id, draft, raw_markdown=draft_text)
            self.plan_state.plan_file_path = str(path)
            if self.plan_state.plan_file_path not in self.plan_state.plan_file_versions:
                self.plan_state.plan_file_versions.append(self.plan_state.plan_file_path)
        except Exception as e:
            logger.warning("Failed to write plan file: %s", e)

        self.plan_state.structured_plan = draft
        self.plan_state.todos = todos
        self.plan_state.draft = draft_text
        self.plan_state.pending_clarification = False
        self.plan_state.transition_to("awaiting_approval")
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
            self.chat_mode = chat_mode
        if thinking_intensity in ("low", "medium", "high"):
            self.thinking_intensity = thinking_intensity

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

            # Auto-dispatch: Personal Agent detects code intent → suggest switching to Coding
            if self._agent_type == "personal" and project and self.chat_mode != "plan":
                if not getattr(self, "_dispatch_suggested_this_session", False):
                    if AgentSession._detect_code_intent(user_input):
                        self._dispatch_suggested_this_session = True
                        yield self._event(
                            "suggest_agent_switch",
                            {
                                "from": "personal",
                                "to": "coding",
                                "reason": "This task involves code development. The Coding Agent provides a professional engineering workflow with worktree isolation, verification, and review.",
                            },
                            run_id,
                        )

            self._last_user_message = user_input  # Keep original for skill matching
            self._refresh_system_prompt()
            if image_base64:
                user_msg = self.router.build_vision_message(resolved_input, image_base64)
            else:
                user_msg = {"role": "user", "content": resolved_input}
            self.messages.append(user_msg)
            self._trim_messages()

            if self.chat_mode == "plan":
                is_new_plan = self.plan_state.phase in ("idle", "completed")
                if is_new_plan:
                    self.plan_state.mode = "plan"
                    self.plan_state.goal = user_input.strip()[:800]
                    self.plan_state.decisions = {}
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

        active_skills: List[str] = []
        if self._last_user_message:
            project = ProjectManager.get_current()
            active_skills = SkillManager.match_skills(
                self._last_user_message, self.role_id, project is not None
            )

        yield self._event("status", {"status": "thinking"}, run_id)

        finished = False
        plan_turn_done = False
        _files_modified = False
        _verify_called = False
        _unstructured_verification_seen = False
        _verify_gate_fired = False
        _latest_verification: Optional[Dict[str, Any]] = None
        _latest_review: Optional[Dict[str, Any]] = None
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
                        self.messages.append({
                            "role": "user",
                            "content": ss_content
                        })

            tool_schemas = self._filter_tool_schemas_for_plan(get_tool_schemas(self.dynamic_registry, agent_type=self._agent_type))

            # Stream LLM response token-by-token for real-time frontend display
            response = None
            stream_error = None
            try:
                async for token in self.router.chat_completion_stream(
                    messages=self.messages,
                    tools=tool_schemas or None,
                    temperature=0.5,
                    max_tokens=8192,
                    thinking_intensity=ti,
                ):
                    ttype = token.get("type", "")
                    if ttype == "thinking_delta":
                        yield self._event(
                            "reasoning",
                            {"text": token["text"], "skill": active_skills[0] if active_skills else None},
                            run_id,
                        )
                    elif ttype == "text_delta":
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
                            messages=self.messages,
                            temperature=0.5,
                            max_tokens=8192,
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
                yield self._event("error", {"message": "Model returned no response"}, run_id)
                finished = True
                break

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            assistant_msg = {
                "role": "assistant",
                "content": message.get("content") or ""
            }
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            if message.get("reasoning_content"):
                assistant_msg["reasoning_content"] = message["reasoning_content"]
            self.messages.append(assistant_msg)

            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
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
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "[VERIFICATION REQUIRED] You modified files this session but have not run "
                            "verify_project. You MUST run verify_project (or the project test/typecheck "
                            "command) before claiming the task is done. Do not say the task is complete "
                            "without showing verification output."
                        ),
                    })
                    continue
                self._trim_messages()
                self._save()
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

                if self.chat_mode == "plan" and self.plan_state.approved:
                    if self._touch_plan_todo_after_tool(tool_name, tc_result.result_text):
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
                    self._apply_plan_questions(tc_result.metadata.get("questions") or [])
                    yield self._event("plan_questions", {
                        "questions": [q.model_dump() for q in self.plan_state.questions],
                        "phase": self.plan_state.phase,
                        "pending_clarification": self.plan_state.pending_clarification,
                    }, run_id)
                    yield self._event("plan_status", self._plan_event_payload(), run_id)
                    plan_turn_done = True

                elif plan_action == "draft_submitted":
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

            self.messages.extend(tool_results)
            self._trim_messages()
            self._save()
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
        yield self._event("run_completed", {
            "status": completion_status,
            "summary": completion_summary,
            **completion_quality,
        }, run_id)
        close_coding_run(completion_status, completion_summary, completion_quality)
        self._save()

    def _touch_plan_todo_after_tool(self, tool_name: str, result_text: str = "") -> bool:
        """Best-effort todo progression after worker dispatch tools (plan execution). Returns True if todos changed."""
        if self.chat_mode != "plan" or not self.plan_state.todos:
            return False
        if tool_name not in ("dispatch_worker", "dispatch_parallel"):
            return False
        todos = self.plan_state.todos
        changed = False
        # Only advance in_progress → completed when worker signals success, or no acceptance signal at all
        acceptance_fail = "ACCEPTANCE: FAIL" in result_text
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
            for t in todos:
                if t.status != "pending":
                    continue
                deps = t.depends_on or []
                if not deps or all(
                    (self._todo_by_id(d) and self._todo_by_id(d).status == "completed") for d in deps
                ):
                    t.status = "in_progress"
                    changed = True
                    break
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

    async def compact_context(self) -> Optional[str]:
        """Compress long message history into a structured summary.

        Called when message count exceeds COMPACTION_THRESHOLD. Asks the model to
        produce a concise summary, then replaces old messages with that summary,
        keeping the system prompt and the last KEEP_RECENT messages intact.
        """
        COMPACTION_THRESHOLD = 15
        KEEP_RECENT = 3

        user_messages = [m for m in self.messages if m.get("role") != "system"]
        if len(user_messages) < COMPACTION_THRESHOLD:
            return None

        # Separate recent messages to keep, older ones to summarize
        recent = user_messages[-KEEP_RECENT:]
        to_summarize = user_messages[:-KEEP_RECENT]

        if len(to_summarize) < 2:
            return None

        # Build a summarization prompt
        conv_text = ""
        for m in to_summarize:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            conv_text += f"[{role}] {str(content)[:500]}\n"

        summary_messages = [
            {"role": "system", "content": (
                "Summarize the following conversation into a concise paragraph in the SAME "
                "language as the conversation. Include: key decisions, files changed, tools used, "
                "and any important context. Keep it under 300 words.\n\n"
                f"Conversation:\n{conv_text}"
            )},
            {"role": "user", "content": "Please summarize the conversation above."},
        ]

        try:
            response = await self.router.chat_completion_non_stream(
                messages=summary_messages,
                temperature=0.3,
                max_tokens=1024,
            )
            summary = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not summary or len(summary) < 10:
                return None
        except Exception as e:
            logger.warning("Context compaction failed: %s", e)
            return None

        # Rebuild messages: system prompt + summary + recent messages
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        self.messages = system_msgs + [
            {"role": "system", "content": f"## Conversation Summary\n{summary}"},
        ] + recent

        logger.info("Context compacted: %d -> %d messages", len(user_messages), len(self.messages) - len(system_msgs))
        self._save()
        return summary

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
                return True
        return False

    def reset(self):
        self.messages = []
        self.iteration = 0
        self._cancelled = False
        self.chat_mode = "agent"
        self.thinking_intensity = getattr(
            load_config().settings, "thinking_intensity_default", "medium"
        ) or "medium"
        if self.thinking_intensity not in ("low", "medium", "high"):
            self.thinking_intensity = "medium"
        self.plan_state = PlanState()
        self._plan_exec_hint_sent = False
        self._repo_map_cache = None
        self._setup_system_prompt()
        self._save()

    def switch_agent(self, agent_type: str):
        """Switch the active agent type, model, thinking intensity, and refresh the system prompt."""
        AgentManager.switch_agent(self, agent_type)

        # Switch to the agent's configured model
        effective = self._resolve_agent_model()
        if effective != self.model_id:
            self.model_id = effective
            try:
                self.router = ModelRouter(effective)
            except ValueError:
                pass  # Keep existing router if new model is unrecognised

        # Update thinking intensity for the new agent
        ti = get_thinking_intensity_for_agent(agent_type)
        if ti in ("low", "medium", "high"):
            self.thinking_intensity = ti

        self._save()

    def switch_role(self, role_id: str):
        """Backward-compatible alias for switch_agent."""
        agent_type = AgentManager.get_agent_type_for_role(role_id)
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

            # Restore per-agent model and thinking intensity from persisted data
            stored_agent_models = data.get("agent_models")
            if isinstance(stored_agent_models, dict):
                for at in ("personal", "coding"):
                    if at in stored_agent_models:
                        session._agent_models[at] = stored_agent_models[at]
            stored_agent_thinking = data.get("agent_thinking")
            if isinstance(stored_agent_thinking, dict):
                for at in ("personal", "coding"):
                    if at in stored_agent_thinking:
                        session._agent_thinking[at] = stored_agent_thinking[at]

            cm = data.get("chat_mode", "agent")
            session.chat_mode = cm if cm in ("agent", "plan") else "agent"
            ti = data.get("thinking_intensity", "medium")
            session.thinking_intensity = ti if ti in ("low", "medium", "high") else "medium"
            ps = data.get("plan_state")
            if isinstance(ps, dict):
                try:
                    session.plan_state = PlanState.model_validate(ps)
                except Exception:
                    session.plan_state = PlanState()
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
        session.switch_agent(resolved_agent_type)
        changed = True
    elif provided_role_id and role_id != session.role_id:
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
