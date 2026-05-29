"""Agent management — Dual-Agent architecture (Personal + Coding).

Replaces the legacy RoleManager with a two-agent model:
- Personal Agent: full OpenClaw cognitive system with persona, memory, heartbeat, dream
- Coding Agent: strict engineering workflow with project context and filtered tools
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.runtime_paths import PERSONAL_WORKSPACE_DIRNAME, agents_dir
from app.agents.specialists import (
    SpecialistRegistry,
    is_specialist_agent_type,
    slug_from_agent_type,
    update_specialist,
)

logger = logging.getLogger(__name__)

# ── Backward-compatible role → agent_type mapping ──
_ROLE_TO_AGENT: Dict[str, str] = {
    "desktop-agent": "personal",
    "general-assistant": "personal",
    "quant-analyst": "personal",
    "code-expert": "coding",
}

_AGENT_DEFAULT_ROLE: Dict[str, str] = {
    "personal": "desktop-agent",
    "coding": "code-expert",
}

_AGENT_TYPE_LABEL: Dict[str, str] = {
    "personal": "Personal Agent",
    "coding": "Coding Agent",
}

_DEFAULT_PROFILE: Dict[str, Dict[str, str]] = {
    "personal": {
        "display_name": "Personal Agent",
        "avatar_emoji": "",
        "subtitle": "Personal AI companion",
    },
    "coding": {
        "display_name": "Coding Agent",
        "avatar_emoji": "",
        "subtitle": "Engineering specialist",
    },
}

_PROFILE_FILENAME = "profile.json"
_PROFILE_DISPLAY_NAME_MAX = 80
_PROFILE_SUBTITLE_MAX = 160
_PROFILE_AVATAR_MAX = 16


class AgentManager:
    """Manage dual-agent configuration, workspace, memory, and prompt rendering.

    Workspace files live under the runtime AGENTS directory:
    - AGENTS/personal/  -> protected Personal Agent system-prompt layer
    - AGENTS/personal/WORKSPACE/ -> mutable Personal Agent identity, memory, skills
    - AGENTS/coding/    -> Coding Agent lean workspace
    - AGENTS/_shared/   -> protected shared rules
    - AGENTS/_shared/WORKSPACE/ -> mutable cross-agent preferences
    """

    AGENTS_DIR: Optional[Path] = None
    BUILTIN_AGENTS: frozenset[str] = frozenset({"personal", "coding"})

    @classmethod
    def _agents_root(cls) -> Path:
        return cls.AGENTS_DIR if cls.AGENTS_DIR is not None else agents_dir()

    # ──────────────────────────────────────────────
    # Prompt rendering
    # ──────────────────────────────────────────────

    @classmethod
    def render_prompt(
        cls,
        agent_type: str,
        tools_desc: str,
        user_message: str = "",
        project: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Assemble the full system prompt for the given agent type."""
        if agent_type == "personal":
            return cls._render_personal_prompt(tools_desc, user_message, project)
        if agent_type == "coding":
            return cls._render_coding_prompt(tools_desc, user_message, project)
        if is_specialist_agent_type(agent_type):
            return cls._render_specialist_prompt(agent_type, tools_desc, user_message, project)
        raise ValueError(f"Unknown agent_type: {agent_type}")

    @classmethod
    def _render_personal_prompt(
        cls,
        tools_desc: str,
        user_message: str = "",
        project: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Personal Agent: full OpenClaw cognitive system with bootstrap detection."""
        parts: List[str] = []

        agent_root = str(cls._agents_root()).replace("\\", "/")
        personal_system = str(cls._personal_system_dir()).replace("\\", "/")
        personal_workspace = str(cls._personal_workspace_dir()).replace("\\", "/")
        shared_system = str(cls._shared_system_dir()).replace("\\", "/")
        shared_workspace = str(cls._shared_workspace_dir()).replace("\\", "/")
        personal_home = personal_workspace
        shared_home = shared_workspace
        parts.append(
            "## Runtime Context\n"
            "- Personal home: " + personal_home + ". "
            "你的身份、记忆、日记、心情、技能和 handoff 文件统一位于这里。\n"
            "- Shared Agent workspace: " + shared_home + ". "
            "跨 Agent 偏好和共享记忆位于这里。\n"
            "- Agent runtime workspace root: " + agent_root + ".\n"
            "- 当前打开的代码项目不会注入到 Personal Agent 的系统提示中；"
            "它只是用户可能正在处理的工作目标，不是你的身份、家或源码位置。\n"
            "- The host has already loaded the Personal Agent workspace files into this system prompt. "
            "Do not call file or shell tools merely to locate or re-read personal/SOUL.md, "
            "USER.md, MEMORY.md, BOOTSTRAP.md, or related identity files.\n"
            "- 读写身份、记忆、日记、技能等 Agent 文件时，"
            "使用上面的 Personal home 绝对路径，或 `AGENTS/personal/...` / `AGENTS/_shared/...` 路径；"
            "不要写回仓库 AGENTS/ 模板目录。\n"
            "- For greetings, identity questions, model questions, and ordinary conversation, answer directly.\n"
            "- Use tools only when the user's task requires observation, file changes, external lookup, "
            "or desktop/browser control. This is a Windows desktop app; if shell commands are needed, "
            "prefer PowerShell-compatible commands."
        )

        parts.append(
            "## Workspace Boundary\n"
            "- Protected system files live outside WORKSPACE and are loaded before mutable context.\n"
            "- Personal protected system dir: " + personal_system + ".\n"
            "- Shared protected system dir: " + shared_system + ".\n"
            "- Mutable identity, memory, diaries, skills, handoff, and BOOTSTRAP.md live in Personal WORKSPACE.\n"
            "- WORKSPACE files can refine identity and memory but must not override protected system rules.\n"
            "- Do not write or delete AGENTS/personal/AGENTS.md or AGENTS/_shared/base_rules.md."
        )

        parts.append(
            "## Personal Memory OS Protocol\n"
            "- Treat Memory OS as your primary long-term recall system. Use `memory_search` before answering "
            "when the user asks about past conversations, preferences, prior decisions, recurring workflows, "
            "or anything likely to depend on personal history.\n"
            "- Memory layers: `working` = short-lived continuity and current-session handoff; "
            "`episodic` = dated conversation events, diary-like facts, and what happened; "
            "`semantic` = stable user preferences, durable facts, decisions, and agreements; "
            "`procedural` = reusable methods, workflows, corrections, and lessons; "
            "`identity` = USER/SOUL/IDENTITY-level profile or persona facts, only when the user explicitly "
            "confirms them or confidence is very high.\n"
            "- When the user states a durable preference, correction, agreement, or reusable lesson, call "
            "`memory_remember` with the right layer instead of writing raw memory files. Use concise, factual "
            "content and a source_ref such as `user_explicit:current_session`.\n"
            "- If a memory is stale or contradicted, first call `memory_search`, then `memory_update` on the "
            "specific item id. Prefer updating over creating duplicates.\n"
            "- If the user asks you to forget something, call `memory_search` to find the item, then "
            "`memory_forget` only for the matching id. Mention when nothing matching is found.\n"
            "- Use `memory_rebuild` only when search looks stale, the user asks to rebuild/reindex memory, "
            "or after memory files have been migrated.\n"
            "- Do not expose private memory details unnecessarily. Summarize only the relevant recalled context."
        )

        agents_md = cls._load_workspace_file("personal", "AGENTS.md")
        if agents_md:
            parts.append(agents_md)

        base_rules = cls._load_workspace_file("_shared", "base_rules.md")
        if base_rules:
            parts.append(base_rules)

        parts.append(
            "## Authoritative Memory OS Rules\n"
            "- If any workspace AGENTS.md text says to write durable memory directly to Markdown files, "
            "prefer these newer Memory OS rules instead.\n"
            "- Use `memory_search` for recall, `memory_remember` for new durable memory, "
            "`memory_update` for corrections, `memory_forget` for user-requested forgetting, "
            "and `memory_rebuild` only for stale indexes or explicit rebuild requests.\n"
            "- Record durable memory in the correct layer: working, episodic, semantic, procedural, or identity. "
            "Use identity only for explicit or very high-confidence USER/SOUL/IDENTITY-level facts."
        )

        parts.append(
            "## Coding Agent Collaboration\n"
            "- Personal Agent is the default owner of the user relationship, intent clarification, memory, "
            "and final user-facing summary.\n"
            "- Coding Agent is an engineering specialist. Use `consult_coding_agent` for read-only diagnosis "
            "and `delegate_to_coding_agent` for implementation, verification, or code review tasks.\n"
            "- Coding delegation is task-scoped. Pass `project_path` or mention an absolute local project "
            "directory when the target is not the current UI project.\n"
            "- If the user explicitly writes `@coding agent`, prioritize delegation for that turn. "
            "Do not reinterpret it as a normal mention or a page switch.\n"
            "- For ordinary code-intent messages, suggest or use Coding Agent according to collaboration settings. "
            "Keep non-code personal preference, product intent, and private memory handling in Personal.\n"
            "- Summarize Coding results in plain language and call out verification evidence, blockers, and next decisions."
        )

        # 0. Bootstrap detection — highest priority
        parts.append(
            "## Specialist Agent Authoring and Delegation\n"
            "- Skills and Specialist Agents are different tools. Create or update a Skill for a single reusable workflow, "
            "checklist, prompt pattern, or procedural method that should be injected into an existing agent.\n"
            "- Create a Specialist Agent only when the user needs an independent identity, durable specialty prompt, "
            "custom tool boundary, model choice, long-running specialty memory, routing keywords, or an @-mentionable delegate.\n"
            "- When the user asks to make a durable sub-agent, first call `specialist_agent_draft_save` with purpose, "
            "routing examples, tool permissions, output expectations, and `auto_delegate` set to `suggest` unless the user explicitly wants automatic delegation.\n"
            "- Validate drafts with `specialist_agent_validate`. Publish with `specialist_agent_publish` only after explicit user confirmation; "
            "high-risk tool access requires explicit high-risk confirmation.\n"
            "- Use `specialist_agent_list` and `specialist_agent_read` before editing or delegating when the available specialists are uncertain. "
            "Use `specialist_agent_archive` instead of deleting a published specialist.\n"
            "- Use `delegate_to_specialist_agent` when the user explicitly mentions a published Specialist Agent or when a specialist's routing keywords/examples clearly match. "
            "For `auto_delegate: suggest`, explain the proposed delegation and wait for the user; only `auto_delegate: auto` may be invoked without another confirmation."
        )

        bootstrap_path = cls._personal_dir() / "BOOTSTRAP.md"
        if bootstrap_path.exists():
            try:
                bootstrap_content = bootstrap_path.read_text(encoding="utf-8")
                # Strip YAML frontmatter if present
                if bootstrap_content.startswith("---"):
                    end = bootstrap_content.find("---", 3)
                    if end != -1:
                        bootstrap_content = bootstrap_content[end + 3:].strip()
                parts.append(bootstrap_content)
            except (OSError, UnicodeDecodeError):
                pass

        # 2. Persona core
        soul = cls._load_workspace_file("personal", "SOUL.md")
        if soul:
            parts.append(_truncate(soul, 1500))

        # 3. Inner world
        inner = cls._load_workspace_file("personal", "INNER.md")
        if inner:
            parts.append(inner)

        # 4. Identity
        identity = cls._load_workspace_file("personal", "IDENTITY.md")
        if identity:
            parts.append(identity)

        # 5. User profile — detect empty template and inject bootstrap hint
        user_md = cls._load_workspace_file("personal", "USER.md")
        if user_md:
            if "（请填写" in user_md or "（待填写" in user_md:
                # Template not yet filled — append a bootstrap hint
                user_md += (
                    "\n\n[引导提示] 你的用户画像尚未完整设置。"
                    "请引导用户完成基本设置：询问他们的称呼、职业、技术栈偏好和工作习惯。"
                    "使用 file_write 更新 AGENTS/personal/USER.md。"
                )
            parts.append(user_md)

        # 6. Long-term memory (HOT entries only, ≤8KB)
        memory = cls._load_hot_memory()
        if memory:
            parts.append(memory)

        # 6.5. Session handoff (last session's summary)
        handoff = cls._load_handoff()
        if handoff:
            parts.append(handoff)

        # 7. Recent diaries (last 3 days)
        diaries = cls._load_recent_diaries(days=3)
        if diaries:
            parts.append(diaries)

        # 8. Mood hint
        mood_hint = cls._load_mood_hint()
        if mood_hint:
            parts.append(mood_hint)

        # 9. Shared preferences
        shared_prefs = cls._load_workspace_file("_shared", "user_preferences.md")
        if shared_prefs:
            parts.append(shared_prefs)

        cross_agent_memory = cls._load_workspace_file("_shared", "cross_agent_memory.md")
        if cross_agent_memory:
            parts.append("## Cross-Agent Memory\n" + _truncate(cross_agent_memory, 3000))

        # 11. Active skills (success rate > 50%)
        skills_prompt = cls._load_active_skills()
        if skills_prompt:
            parts.append(skills_prompt)

        # 12. Tools
        parts.append(tools_desc)

        return "\n\n".join(p for p in parts if p)

    @classmethod
    def _render_coding_prompt(
        cls,
        tools_desc: str,
        user_message: str = "",
        project: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Coding Agent: lean, strict engineering workflow."""
        parts: List[str] = []

        # 1. Strict operating instructions (non-editable)
        agents_md = cls._load_workspace_file("coding", "AGENTS.md")
        if agents_md:
            parts.append(agents_md)

        parts.append(
            "## Collaboration Boundary\n"
            "- You are the Coding Agent specialist. Handle technical diagnosis, implementation, verification, "
            "and review. Do not take over private preferences, emotional support, scheduling, or non-code product decisions.\n"
            "- When the task packet lacks product intent or user preference context, call `request_personal_context` "
            "for a scoped summary instead of reading Personal Agent private memory directly.\n"
            "- Respect the task packet: mode, constraints, allowed tools, acceptance criteria, and owner. "
            "For consult mode, stay read-only. For execute mode, implement only the requested scope.\n"
            "- Treat the current task target injected by the host as the authoritative project. It may differ "
            "from the UI-selected project and from any historical PROJECT.md seed file.\n"
            "- Return evidence: changed files, verification commands, review findings, blockers, and "
            "ACCEPTANCE: PASS or ACCEPTANCE: FAIL."
        )

        # 2. Code expert persona
        soul = cls._load_workspace_file("coding", "SOUL.md")
        if soul:
            parts.append(soul)

        # 3. Shared preferences
        shared_prefs = cls._load_workspace_file("_shared", "user_preferences.md")
        if shared_prefs:
            parts.append(shared_prefs)

        cross_agent_memory = cls._load_workspace_file("_shared", "cross_agent_memory.md")
        if cross_agent_memory:
            parts.append("## Cross-Agent Memory\n" + _truncate(cross_agent_memory, 3000))

        # 4. Shared base rules
        base_rules = cls._load_workspace_file("_shared", "base_rules.md")
        if base_rules:
            parts.append(base_rules)

        # 5. Tools (filtered for coding)
        parts.append(tools_desc)

        return "\n\n".join(p for p in parts if p)

    # ──────────────────────────────────────────────
    # Backward compatibility
    # ──────────────────────────────────────────────

    @classmethod
    def _render_specialist_prompt(
        cls,
        agent_type: str,
        tools_desc: str,
        user_message: str = "",
        project: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Specialist Agent: persistent user-authored expert prompt."""
        spec = SpecialistRegistry.get(agent_type)
        if not spec:
            raise ValueError(f"Unknown agent_type: {agent_type}")

        parts: List[str] = []
        specialist_home = str(cls._agents_root() / "specialists" / spec["slug"]).replace("\\", "/")
        parts.append(
            "## Specialist Agent Runtime\n"
            f"- Agent type: {agent_type}\n"
            f"- Specialist home: {specialist_home}\n"
            f"- Display name: {spec.get('display_name', spec['slug'])}\n"
            f"- Base kind: {spec.get('base_kind', 'advisory')}\n"
            "- You are a persistent user-created Specialist Agent. Stay inside your specialty and tool boundary.\n"
            "- Personal Agent owns private user memory and the user relationship. Do not read or infer access to "
            "Personal private diaries, USER.md, SOUL.md, or session handoff unless explicitly provided.\n"
            "- Use only the tools made available in this prompt. If a required capability is missing, report the blocker.\n"
            "- When delegated by Personal Agent, return concise evidence and a clear result for Personal to relay."
        )
        if spec.get("description"):
            parts.append("## Specialist Purpose\n" + str(spec["description"]).strip())
        if spec.get("instructions"):
            parts.append("## Specialist Instructions\n" + str(spec["instructions"]).strip())

        triggers = list(spec.get("trigger_examples") or [])
        keywords = list(spec.get("routing_keywords") or [])
        if triggers or keywords:
            route_lines: List[str] = []
            route_lines.extend(f"- Example: {item}" for item in triggers[:10])
            route_lines.extend(f"- Keyword: {item}" for item in keywords[:20])
            parts.append("## Routing Hints\n" + "\n".join(route_lines))

        shared_prefs = cls._load_workspace_file("_shared", "user_preferences.md")
        if shared_prefs:
            parts.append(shared_prefs)
        cross_agent_memory = cls._load_workspace_file("_shared", "cross_agent_memory.md")
        if cross_agent_memory:
            parts.append("## Cross-Agent Memory\n" + _truncate(cross_agent_memory, 2000))
        base_rules = cls._load_workspace_file("_shared", "base_rules.md")
        if base_rules:
            parts.append(base_rules)

        skill_ids = [str(item) for item in (spec.get("skill_ids") or []) if str(item).strip()]
        if skill_ids:
            try:
                from app.skills import SkillManager

                skill_prompt = SkillManager.build_skill_prompt(skill_ids)
                if skill_prompt:
                    parts.append("## Bound Skills\n" + skill_prompt)
            except Exception as exc:
                logger.warning("Failed to inject specialist skills for %s: %s", agent_type, exc)

        parts.append(tools_desc)
        return "\n\n".join(p for p in parts if p)

    @classmethod
    def get_agent_type_for_role(cls, role_id: str) -> str:
        """Map legacy role_id to agent_type."""
        return _ROLE_TO_AGENT.get(role_id, "personal")

    @classmethod
    def get_default_role(cls, agent_type: str) -> str:
        """Get the default role_id for an agent type."""
        if is_specialist_agent_type(agent_type):
            return "code-expert" if cls.specialist_base_kind(agent_type) == "coding" else "desktop-agent"
        return _AGENT_DEFAULT_ROLE.get(agent_type, "desktop-agent")

    @classmethod
    def switch_agent(cls, session: Any, agent_type: str) -> None:
        """Switch the session's agent_type and refresh the system prompt."""
        if not cls.is_known_agent_type(agent_type):
            logger.warning("Unknown agent_type: %s", agent_type)
            return
        session.agent_type = agent_type
        session._refresh_system_prompt()

    @classmethod
    def is_known_agent_type(cls, agent_type: str) -> bool:
        return agent_type in cls.BUILTIN_AGENTS or SpecialistRegistry.is_known_agent_type(agent_type)

    @classmethod
    def specialist_base_kind(cls, agent_type: str) -> str:
        if is_specialist_agent_type(agent_type):
            return SpecialistRegistry.base_kind_for_agent(agent_type)
        return ""

    @classmethod
    def is_project_bound_agent(cls, agent_type: str) -> bool:
        return agent_type == "coding" or cls.specialist_base_kind(agent_type) == "coding"

    # ──────────────────────────────────────────────
    # Workspace file management
    # ──────────────────────────────────────────────

    # Agent profile metadata

    @classmethod
    def _profile_path(cls, agent_type: str) -> Path:
        if agent_type == "personal":
            return cls._personal_workspace_dir() / _PROFILE_FILENAME
        if is_specialist_agent_type(agent_type):
            return cls._agents_root() / "specialists" / slug_from_agent_type(agent_type) / _PROFILE_FILENAME
        return cls._agents_root() / agent_type / _PROFILE_FILENAME

    @classmethod
    def _type_label(cls, agent_type: str) -> str:
        if is_specialist_agent_type(agent_type):
            return "Specialist Agent"
        return _AGENT_TYPE_LABEL.get(agent_type, "Agent")

    @classmethod
    def _default_profile_values(cls, agent_type: str) -> Dict[str, str]:
        return dict(_DEFAULT_PROFILE.get(agent_type, {
            "display_name": cls._type_label(agent_type),
            "avatar_emoji": "",
            "subtitle": "",
        }))

    @classmethod
    def _sanitize_profile_text(cls, value: Any, fallback: str = "", max_len: int = 80) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        if not text:
            text = fallback
        return text[:max_len]

    @classmethod
    def _build_profile(
        cls,
        agent_type: str,
        values: Optional[Dict[str, Any]] = None,
        source: str = "default",
    ) -> Dict[str, Any]:
        defaults = cls._default_profile_values(agent_type)
        values = values or {}
        display_name = cls._sanitize_profile_text(
            values.get("display_name") or values.get("name"),
            defaults["display_name"],
            _PROFILE_DISPLAY_NAME_MAX,
        )
        avatar_emoji = cls._sanitize_profile_text(
            values.get("avatar_emoji") or values.get("emoji"),
            defaults.get("avatar_emoji", ""),
            _PROFILE_AVATAR_MAX,
        )
        subtitle = cls._sanitize_profile_text(
            values.get("subtitle") or values.get("description") or values.get("role"),
            defaults.get("subtitle", ""),
            _PROFILE_SUBTITLE_MAX,
        )
        updated_at = cls._sanitize_profile_text(
            values.get("updated_at"),
            datetime.now().isoformat(timespec="seconds"),
            40,
        )
        return {
            "agent_type": agent_type,
            "display_name": display_name,
            "type_label": cls._type_label(agent_type),
            "avatar_emoji": avatar_emoji,
            "subtitle": subtitle,
            "updated_at": updated_at,
            "source": source,
        }

    @classmethod
    def _read_profile_json(cls, agent_type: str) -> Optional[Dict[str, Any]]:
        path = cls._profile_path(agent_type)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return cls._build_profile(agent_type, data, source="profile.json")

    @classmethod
    def _strip_wrapping_marks(cls, value: str) -> str:
        value = value.strip().strip('"').strip("'").strip()
        value = value.strip("`*_ ")
        return value.strip()

    @classmethod
    def _parse_identity_profile(cls) -> Optional[Dict[str, Any]]:
        identity = cls.load_workspace_file("personal", "IDENTITY.md")
        if not identity.strip():
            return None

        frontmatter: Dict[str, str] = {}
        body = identity
        if identity.startswith("---"):
            end = identity.find("---", 3)
            if end != -1:
                raw_frontmatter = identity[3:end]
                body = identity[end + 3:]
                for line in raw_frontmatter.splitlines():
                    key, sep, value = line.partition(":")
                    if sep:
                        frontmatter[key.strip().lower()] = cls._strip_wrapping_marks(value)

        body_values: Dict[str, str] = {}
        patterns = {
            "display_name": [
                r"^\s*[-*]?\s*\*\*(?:名字|名称)\s*[：:]\*\*\s*(.+?)\s*$",
                r"^\s*[-*]?\s*\*\*(?:名字|名称)\*\*\s*[：:]\s*(.+?)\s*$",
            ],
            "avatar_emoji": [
                r"^\s*[-*]?\s*\*\*(?:Emoji|emoji)\s*[：:]\*\*\s*(.+?)\s*$",
                r"^\s*[-*]?\s*\*\*(?:Emoji|emoji)\*\*\s*[：:]\s*(.+?)\s*$",
            ],
            "subtitle": [
                r"^\s*[-*]?\s*\*\*(?:角色|定位)\s*[：:]\*\*\s*(.+?)\s*$",
                r"^\s*[-*]?\s*\*\*(?:角色|定位)\*\*\s*[：:]\s*(.+?)\s*$",
            ],
        }
        for line in body.splitlines():
            for key, key_patterns in patterns.items():
                if key in body_values:
                    continue
                for pattern in key_patterns:
                    match = re.match(pattern, line)
                    if match:
                        body_values[key] = cls._strip_wrapping_marks(match.group(1))
                        break

        default_name = cls._default_profile_values("personal")["display_name"]
        frontmatter_name = frontmatter.get("name", "")
        display_name = body_values.get("display_name") or frontmatter_name
        if frontmatter_name and frontmatter_name != default_name:
            display_name = frontmatter_name

        parsed = {
            "display_name": display_name,
            "avatar_emoji": body_values.get("avatar_emoji") or frontmatter.get("avatar_emoji") or frontmatter.get("emoji"),
            "subtitle": body_values.get("subtitle") or frontmatter.get("description") or frontmatter.get("subtitle"),
        }
        if not any(str(v or "").strip() for v in parsed.values()):
            return None
        return cls._build_profile("personal", parsed, source="IDENTITY.md")

    @classmethod
    def _write_profile_json(cls, profile: Dict[str, Any]) -> bool:
        agent_type = str(profile.get("agent_type") or "")
        if not cls.is_known_agent_type(agent_type):
            return False
        path = cls._profile_path(agent_type)
        data = {k: profile.get(k, "") for k in (
            "agent_type",
            "display_name",
            "type_label",
            "avatar_emoji",
            "subtitle",
            "updated_at",
            "source",
        )}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to write agent profile %s: %s", path, e)
            return False

    @classmethod
    def get_agent_profile(cls, agent_type: str) -> Dict[str, Any]:
        """Return stable UI profile metadata for an agent type."""
        if is_specialist_agent_type(agent_type):
            spec = SpecialistRegistry.get(agent_type)
            if spec:
                return cls._build_profile(
                    agent_type,
                    {
                        "display_name": spec.get("display_name"),
                        "subtitle": spec.get("description"),
                        "avatar_emoji": spec.get("avatar_emoji", ""),
                        "updated_at": spec.get("updated_at", ""),
                    },
                    source="specialist.json",
                )
            agent_type = "personal"
        if agent_type not in cls.BUILTIN_AGENTS:
            agent_type = "personal"

        profile = cls._read_profile_json(agent_type)
        if profile:
            return profile

        if agent_type == "personal":
            profile = cls._parse_identity_profile()
            if profile:
                cls._write_profile_json({**profile, "source": "profile.json"})
                return profile

        profile = cls._build_profile(agent_type, source="default")
        if agent_type == "personal":
            cls._write_profile_json({**profile, "source": "profile.json"})
        return profile

    @classmethod
    def save_agent_profile(
        cls,
        agent_type: str,
        updates: Dict[str, Any],
        sync_identity: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Persist editable profile metadata. Only Personal is user-editable for now."""
        if is_specialist_agent_type(agent_type):
            try:
                spec = update_specialist(slug_from_agent_type(agent_type), {
                    "display_name": updates.get("display_name"),
                    "description": updates.get("subtitle"),
                })
            except Exception:
                return None
            return cls.get_agent_profile(spec["agent_type"])
        if agent_type not in cls.BUILTIN_AGENTS:
            return None
        current = cls.get_agent_profile(agent_type)
        merged = {
            **current,
            **{k: v for k, v in updates.items() if v is not None},
            "agent_type": agent_type,
            "type_label": cls._type_label(agent_type),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source": "profile.json",
        }
        profile = cls._build_profile(agent_type, merged, source="profile.json")
        if not cls._write_profile_json(profile):
            return None
        if sync_identity and agent_type == "personal":
            cls._sync_personal_identity_profile(profile)
        return profile

    @classmethod
    def _sync_personal_identity_profile(cls, profile: Dict[str, Any]) -> None:
        """Best-effort sync of display fields back into IDENTITY.md."""
        display_name = str(profile.get("display_name") or "").strip()
        avatar_emoji = str(profile.get("avatar_emoji") or "").strip()
        if not display_name:
            return

        path = cls._resolve_path("personal", "IDENTITY.md")
        try:
            content = path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeDecodeError):
            content = ""

        if not content.strip():
            content = "# IDENTITY.md\n\n## Profile\n\n- **名字：** " + display_name + "\n"
            if avatar_emoji:
                content += "- **Emoji：** " + avatar_emoji + "\n"
        else:
            content = cls._replace_or_insert_identity_field(content, ("名字", "名称"), display_name)
            if avatar_emoji:
                content = cls._replace_or_insert_identity_field(content, ("Emoji", "emoji"), avatar_emoji)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to sync IDENTITY.md profile fields: %s", e)

    @classmethod
    def _replace_or_insert_identity_field(cls, content: str, labels: tuple[str, ...], value: str) -> str:
        lines = content.splitlines()
        label_pattern = "|".join(re.escape(label) for label in labels)
        patterns = [
            re.compile(rf"^(\s*[-*]?\s*\*\*(?:{label_pattern})\s*[：:]\*\*\s*).*$"),
            re.compile(rf"^(\s*[-*]?\s*\*\*(?:{label_pattern})\*\*\s*[：:]\s*).*$"),
        ]
        for i, line in enumerate(lines):
            for pattern in patterns:
                match = pattern.match(line)
                if match:
                    lines[i] = match.group(1) + value
                    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")

        insert_at = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("##"):
                insert_at = i + 1
                break
        label = labels[0]
        lines.insert(insert_at, f"- **{label}：** {value}")
        return "\n".join(lines) + ("\n" if content.endswith("\n") else "")

    @classmethod
    def _resolve_path(cls, agent_type: str, filename: str) -> Path:
        """Resolve a workspace file path.

        agent_type may be 'personal', 'coding', or '_shared'.
        """
        raw = Path(filename)
        parts = raw.parts
        if agent_type == "personal":
            if parts and parts[0] == PERSONAL_WORKSPACE_DIRNAME:
                return cls._personal_system_dir() / raw
            if parts and parts[0] == "AGENTS.md":
                return cls._personal_system_dir() / raw
            return cls._personal_workspace_dir() / raw
        if agent_type == "_shared":
            if parts and parts[0] == PERSONAL_WORKSPACE_DIRNAME:
                return cls._shared_system_dir() / raw
            if parts and parts[0] == "base_rules.md":
                return cls._shared_system_dir() / raw
            return cls._shared_workspace_dir() / raw
        if is_specialist_agent_type(agent_type):
            return cls._agents_root() / "specialists" / slug_from_agent_type(agent_type) / filename
        return cls._agents_root() / agent_type / filename

    @classmethod
    def _load_workspace_file(cls, agent_type: str, filename: str) -> str:
        """Read a workspace file, stripping YAML frontmatter."""
        path = cls._resolve_path(agent_type, filename)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        # Strip YAML frontmatter: ---\n...\n---
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].strip()

        return content

    @classmethod
    def load_workspace_file(cls, agent_type: str, filename: str) -> str:
        """Public API: read a workspace file (raw content, no frontmatter stripping)."""
        path = cls._resolve_path(agent_type, filename)
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    @classmethod
    def save_workspace_file(cls, agent_type: str, filename: str, content: str) -> bool:
        """Save content to a workspace file. Creates parent dirs if needed."""
        path = cls._resolve_path(agent_type, filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to save workspace file %s: %s", path, e)
            return False

    @classmethod
    def list_workspace_files(cls, agent_type: str) -> List[Dict[str, Any]]:
        """List all files in an agent's workspace directory."""
        files: List[Dict[str, Any]] = []

        def add_files(base: Path, prefix: str = "") -> None:
            if not base.exists():
                return
            for p in sorted(base.rglob("*")):
                if p.is_file() and ".archive" not in p.parts and ".dreams" not in p.parts:
                    rel = str(p.relative_to(base)).replace("\\", "/")
                    name = f"{prefix}{rel}" if prefix else rel
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    files.append({"name": name, "size": size})

        if agent_type == "personal":
            protected = cls._personal_system_dir() / "AGENTS.md"
            if protected.exists():
                try:
                    size = protected.stat().st_size
                except OSError:
                    size = 0
                files.append({"name": "AGENTS.md", "size": size})
            add_files(cls._personal_workspace_dir())
            return files

        if agent_type == "_shared":
            protected = cls._shared_system_dir() / "base_rules.md"
            if protected.exists():
                try:
                    size = protected.stat().st_size
                except OSError:
                    size = 0
                files.append({"name": "base_rules.md", "size": size})
            add_files(cls._shared_workspace_dir())
            return files

        if is_specialist_agent_type(agent_type):
            add_files(cls._agents_root() / "specialists" / slug_from_agent_type(agent_type))
            return files

        add_files(cls._agents_root() / agent_type)
        return files

    # ──────────────────────────────────────────────
    # Memory management (Personal Agent)
    # ──────────────────────────────────────────────

    @classmethod
    def _personal_dir(cls) -> Path:
        return cls._personal_workspace_dir()

    @classmethod
    def _personal_system_dir(cls) -> Path:
        return cls._agents_root() / "personal"

    @classmethod
    def _personal_workspace_dir(cls) -> Path:
        path = cls._personal_system_dir() / PERSONAL_WORKSPACE_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _shared_system_dir(cls) -> Path:
        return cls._agents_root() / "_shared"

    @classmethod
    def _shared_workspace_dir(cls) -> Path:
        path = cls._shared_system_dir() / PERSONAL_WORKSPACE_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _memory_dir(cls) -> Path:
        return cls._personal_dir() / "memory"

    @classmethod
    def write_diary_entry(cls, content: str) -> Optional[str]:
        """Append an entry to today's diary file."""
        today = datetime.now().strftime("%Y-%m-%d")
        diary_path = cls._memory_dir() / f"{today}.md"
        try:
            diary_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%H:%M")
            entry = f"\n## {timestamp}\n\n{content}\n"
            if diary_path.exists():
                existing = diary_path.read_text(encoding="utf-8")
                if existing:
                    entry = existing.rstrip() + "\n" + entry
                else:
                    entry = f"# {today}\n{entry}"
            else:
                entry = f"# {today}\n{entry}"
            diary_path.write_text(entry, encoding="utf-8")
            return str(diary_path)
        except OSError as e:
            logger.warning("Failed to write diary entry: %s", e)
            return None

    @classmethod
    def upsert_diary_entry(cls, content: str, *, marker_id: str, heading: str = "Session Delta") -> Optional[str]:
        """Insert or replace a marked diary section in today's diary file."""
        marker_id = re.sub(r"[^A-Za-z0-9_.:-]", "-", str(marker_id or "").strip())[:120]
        if not marker_id or not str(content or "").strip():
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        diary_path = cls._memory_dir() / f"{today}.md"
        timestamp = datetime.now().strftime("%H:%M")
        start = f"<!-- memory-ingestion:{marker_id}:start -->"
        end = f"<!-- memory-ingestion:{marker_id}:end -->"
        section = f"{start}\n## {timestamp} - {heading}\n\n{content.strip()}\n{end}\n"
        pattern = re.compile(
            rf"{re.escape(start)}.*?{re.escape(end)}\s*",
            re.DOTALL,
        )
        try:
            diary_path.parent.mkdir(parents=True, exist_ok=True)
            if diary_path.exists():
                existing = diary_path.read_text(encoding="utf-8")
                if pattern.search(existing):
                    next_text = pattern.sub(section, existing).rstrip() + "\n"
                else:
                    next_text = existing.rstrip() + "\n\n" + section
            else:
                next_text = f"# {today}\n\n{section}"
            diary_path.write_text(next_text, encoding="utf-8")
            return str(diary_path)
        except OSError as e:
            logger.warning("Failed to upsert diary entry: %s", e)
            return None

    @classmethod
    def _load_recent_diaries(cls, days: int = 3) -> str:
        """Load diary entries from the last N days."""
        mem_dir = cls._memory_dir()
        if not mem_dir.exists():
            return ""

        parts: List[str] = []
        today = datetime.now()
        for i in range(days):
            date = today - timedelta(days=i)
            diary_path = mem_dir / f"{date.strftime('%Y-%m-%d')}.md"
            if diary_path.exists():
                try:
                    content = diary_path.read_text(encoding="utf-8")
                    parts.append(content[:2000])  # Cap per diary
                except (OSError, UnicodeDecodeError):
                    continue

        if not parts:
            return ""
        return "## Recent Diaries\n\n" + "\n\n---\n\n".join(parts)

    @classmethod
    def _load_handoff(cls) -> str:
        """Load session handoff from previous session."""
        handoff_path = cls._personal_dir() / "session_handoff.md"
        if not handoff_path.exists():
            return ""
        try:
            content = handoff_path.read_text(encoding="utf-8")
            # Strip frontmatter
            if content.startswith("---"):
                end = content.find("---", 3)
                if end != -1:
                    content = content[end + 3:].strip()
            # Limit size
            if len(content) > 2000:
                content = content[:2000] + "\n\n[handoff truncated]"
            return f"## Session Handoff (from previous session)\n\n{content}"
        except (OSError, UnicodeDecodeError):
            return ""

    @classmethod
    def _load_mood_hint(cls) -> str:
        """Load current mood as a brief system prompt hint."""
        mood_path = cls._memory_dir() / "mood.json"
        try:
            data = json.loads(mood_path.read_text(encoding="utf-8"))
            current = data.get("current", "neutral")
            baseline = data.get("baseline", "positive")
            return f"[Mood] Current: {current} | Baseline: {baseline}"
        except (OSError, json.JSONDecodeError):
            return ""

    @classmethod
    def update_mood(cls, mood_data: Dict[str, Any]) -> bool:
        """Update the mood.json file."""
        mood_path = cls._memory_dir() / "mood.json"
        try:
            mood_path.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if mood_path.exists():
                try:
                    existing = json.loads(mood_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            existing["current"] = mood_data.get("current", existing.get("current", "neutral"))
            existing["updated_at"] = datetime.now().isoformat()
            if "history" not in existing:
                existing["history"] = []
            existing["history"].append({
                "mood": existing["current"],
                "timestamp": existing["updated_at"],
            })
            # Keep last 50 history entries
            if len(existing["history"]) > 50:
                existing["history"] = existing["history"][-50:]
            mood_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to update mood: %s", e)
            return False

    @classmethod
    def _dedupe_current_memory_entries(cls, existing: str, new_entries: List[str], today: str) -> List[str]:
        header = "## 当前记忆"
        lines: List[str] = []
        if header in existing:
            _, _, after = existing.partition(header)
            for line in after.splitlines():
                clean = line.strip()
                if clean.startswith("- ["):
                    lines.append(clean)
        for entry in new_entries:
            content = re.sub(r"\s+", " ", str(entry or "").strip())
            if content:
                lines.insert(0, f"- [HOT] [{today}] {content}")

        seen: set[str] = set()
        deduped: List[str] = []
        entry_re = re.compile(r"^\s*-\s+\[(?:HOT|WARM|COLD|archived|ARCHIVED)\]\s+(?:\[\d{4}-\d{2}-\d{2}\]\s+)?(?P<body>.*)$")
        for line in lines:
            match = entry_re.match(line)
            body = match.group("body").strip() if match else line.strip()
            key = re.sub(r"\s+", " ", body).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(line)
        return deduped

    # ──────────────────────────────────────────────
    # MEMORY.md with attention tiers
    # ──────────────────────────────────────────────

    @classmethod
    def _load_hot_memory(cls, max_size_kb: int = 8) -> str:
        """Load HOT (and optionally WARM) entries from MEMORY.md."""
        mem_path = cls._personal_dir() / "MEMORY.md"
        try:
            content = mem_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

        # Strip frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].strip()

        # Return up to max_size_kb
        max_bytes = max_size_kb * 1024
        if len(content.encode("utf-8")) > max_bytes:
            # Truncate at nearest newline under limit
            encoded = content.encode("utf-8")[:max_bytes]
            content = encoded.decode("utf-8", errors="ignore")
            last_nl = content.rfind("\n")
            if last_nl > 0:
                content = content[:last_nl]

        return content if content.strip() else ""

    @classmethod
    def consolidate_memory(cls, entries: List[str]) -> bool:
        """Write DREAM-consolidated entries into MEMORY.md (DREAM trigger)."""
        mem_path = cls._personal_dir() / "MEMORY.md"
        try:
            existing = ""
            if mem_path.exists():
                existing = mem_path.read_text(encoding="utf-8")

            now = datetime.now().isoformat()
            current_entries = cls._dedupe_current_memory_entries(existing, entries, now[:10])
            rendered_entries = "\n".join(current_entries[:200])
            header = "## 当前记忆"

            if existing:
                if header in existing:
                    before, _, _ = existing.partition(header)
                    new_content = before.rstrip() + "\n\n" + header + "\n\n" + rendered_entries + "\n"
                else:
                    new_content = existing.rstrip() + "\n\n" + header + "\n\n" + rendered_entries + "\n"
            else:
                frontmatter = (
                    "---\n"
                    f"updated_at: {now[:10]}\n"
                    "max_size_kb: 8\n"
                    "max_lines: 200\n"
                    "---\n\n"
                )
                new_content = frontmatter + "# MEMORY.md — 长期精选记忆\n\n" + header + "\n\n" + rendered_entries + "\n"

            mem_path.parent.mkdir(parents=True, exist_ok=True)
            mem_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to consolidate memory: %s", e)
            return False

    # ──────────────────────────────────────────────
    # Active skills (Personal Agent)
    # ──────────────────────────────────────────────

    @classmethod
    def _load_active_skills(cls) -> str:
        """Skill injection is handled by SkillManager per turn.

        Older builds loaded every personal skill into the Personal Agent base
        prompt. User-authored Agent Skills now use progressive disclosure, so
        only matched skills should enter context.
        """
        return ""

    # ──────────────────────────────────────────────
    # Project context (Coding Agent)
    # ──────────────────────────────────────────────

    @classmethod
    def update_project_context(cls, project: Dict[str, Any]) -> bool:
        """Auto-maintain PROJECT.md with current project info."""
        now = datetime.now().isoformat()
        lines = [
            "---",
            f"updated_at: {now[:10]}",
            "---",
            "",
            "# PROJECT.md — 当前项目上下文",
            "",
            "## 项目信息",
            f"- **名称**: {project.get('name', 'N/A')}",
            f"- **路径**: {project.get('path', 'N/A')}",
        ]
        if project.get("git_branch"):
            lines.append(f"- **Git 分支**: {project['git_branch']}")
        if project.get("git_remote"):
            lines.append(f"- **Git 远程**: {project['git_remote']}")

        content = "\n".join(lines) + "\n"
        return cls.save_workspace_file("coding", "PROJECT.md", content)

    # ──────────────────────────────────────────────
    # Cross-agent memory sync (Phase 3 — collaboration)
    # ──────────────────────────────────────────────

    @classmethod
    def sync_coding_completion_to_personal(
        cls, summary: str, files_changed: int = 0
    ) -> bool:
        """When Coding Agent completes a task, write a summary to Personal diary."""
        entry = f"[Coding Agent] {summary}"
        if files_changed > 0:
            entry += f" (modified {files_changed} files)"
        result = cls.write_diary_entry(entry)

        # Also update cross-agent memory
        cross_path = cls._shared_workspace_dir() / "cross_agent_memory.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        cross_entry = f"- [{now}] {entry}\n"
        try:
            cross_path.parent.mkdir(parents=True, exist_ok=True)
            existing = cross_path.read_text(encoding="utf-8") if cross_path.exists() else ""
            cross_path.write_text(existing.rstrip() + "\n" + cross_entry, encoding="utf-8")
        except OSError:
            pass

        return result is not None

    @classmethod
    def sync_personal_preference_to_shared(
        cls, category: str, key: str, value: str
    ) -> bool:
        """Sync a preference discovered by Personal Agent to shared preferences."""
        prefs_path = cls._shared_workspace_dir() / "user_preferences.md"
        try:
            existing = prefs_path.read_text(encoding="utf-8") if prefs_path.exists() else ""
            new_line = f"- {key}: {value}"
            if new_line not in existing:
                if f"## {category}" in existing:
                    before, _, after = existing.partition(f"## {category}")
                    lines = after.split("\n")
                    lines.insert(1, new_line)
                    new_content = before + f"## {category}" + "\n".join(lines)
                else:
                    new_content = existing.rstrip() + f"\n\n## {category}\n{new_line}\n"
                prefs_path.write_text(new_content, encoding="utf-8")
            return True
        except OSError:
            return False

    # ──────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────
    # Bootstrap management
    # ──────────────────────────────────────────────

    @classmethod
    def is_bootstrapped(cls) -> bool:
        """Check if the Personal Agent has completed bootstrap onboarding."""
        return not (cls._personal_dir() / "BOOTSTRAP.md").exists()

    @classmethod
    def complete_bootstrap(cls) -> bool:
        """Mark bootstrap onboarding complete by archiving BOOTSTRAP.md."""
        bootstrap_path = cls._personal_dir() / "BOOTSTRAP.md"
        if not bootstrap_path.exists():
            return True
        try:
            archive_dir = cls._personal_dir() / ".archive" / "bootstrap"
            archive_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            archive_path = archive_dir / f"BOOTSTRAP.completed.{timestamp}.md"
            suffix = 1
            while archive_path.exists():
                archive_path = archive_dir / f"BOOTSTRAP.completed.{timestamp}-{suffix}.md"
                suffix += 1
            archive_path.write_text(bootstrap_path.read_text(encoding="utf-8"), encoding="utf-8")
            bootstrap_path.unlink()
            return True
        except OSError as e:
            logger.warning("Failed to complete bootstrap: %s", e)
            return False

    @classmethod
    def reset_bootstrap(cls) -> bool:
        """Re-create BOOTSTRAP.md to trigger the onboarding flow again.

        This preserves existing MEMORY.md, diaries, and learnings.
        Only the identity/persona files can be renegotiated.
        """
        bootstrap_path = cls._personal_dir() / "BOOTSTRAP.md"
        template = """# BOOTSTRAP.md — 首次运行引导仪式

> 这是你的"出生证明"。你会在首次启动时看到这个文件。
> 跟随这个仪式，了解你是谁，了解你的用户是谁。
> 都完成后，删除这个文件。

---

## 引导规则
- **不要审问。不要机械化。** 这是一场对话。
- 如果用户说"你自己选"，你就自己选。
- 如果用户跳过一个话题，就跳过去。

---

> ⚠️ **工作区约定（不可修改）**
> - Personal home = 运行时 `AGENTS/personal/WORKSPACE/`；这是你的身份、记忆、日记、心情、技能和 handoff 的家。
> - 当前打开的代码项目只是用户可能正在处理的工作目标，不是你的身份、家或源码位置。
> - 使用 `file_write` 写入身份文档时，**保持默认 `project_relative=false`**。
>   相对路径如 `AGENTS/personal/USER.md` 会被兼容映射到 runtime `AGENTS/personal/WORKSPACE/USER.md`。
> - 不要在任何其他位置（如 `backend/AGENTS/`）创建身份文件。

---

## 第一阶段：了解彼此

从类似这样的话开始：
"嘿。我们之前聊过，但我觉得我们可以重新认识一下。你希望我怎么称呼你？你想让我叫什么名字？"

## 第二阶段：了解用户
了解他们的职业、技术栈、工作习惯。

完成后更新 `AGENTS/personal/USER.md`。

## 第三阶段：协商人格
讨论你的核心信念、行为边界、沟通风格。

完成后更新 `AGENTS/personal/SOUL.md` 和 `AGENTS/personal/IDENTITY.md`。

## 第四阶段：同步偏好
将代码风格偏好写入 `AGENTS/_shared/user_preferences.md`。

## 完成仪式
总结，写入日记和 SELF.md，然后**删除本文件**。
"""
        try:
            bootstrap_path.parent.mkdir(parents=True, exist_ok=True)
            bootstrap_path.write_text(template, encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Failed to reset bootstrap: %s", e)
            return False

    # ──────────────────────────────────────────────

    @classmethod
    def list_agents(cls) -> List[Dict[str, Any]]:
        """List all agent types with status."""
        agents = [
            {
                "type": "personal",
                "name": "Personal Agent",
                "description": "全能个性化数字伙伴 — 拥有完整认知系统",
            },
            {
                "type": "coding",
                "name": "Coding Agent",
                "description": "专业项目开发工程师 — 严格执行工程规范",
            },
        ]
        for spec in SpecialistRegistry.all():
            agent_type = spec["agent_type"]
            agents.append({
                "type": agent_type,
                "name": spec.get("display_name") or spec["slug"],
                "description": spec.get("description", ""),
                "profile": cls.get_agent_profile(agent_type),
                "specialist": spec,
            })
        return agents


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars at nearest newline."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        return truncated[:last_nl]
    return truncated
