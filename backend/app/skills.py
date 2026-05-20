from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from app.runtime_paths import PERSONAL_WORKSPACE_DIRNAME, agents_dir, runtime_file


SKILL_DIR = Path(__file__).parent.parent / "prompts" / "skills"
SKILL_PREFS_PATH = runtime_file("data", "skill_preferences.json")
PERSONAL_SKILL_PREFIX = "personal:"
USER_SKILL_PREFIX = "user:"
AGENT_TYPES: Tuple[str, str] = ("personal", "coding")
MAX_USER_SKILLS_PER_TURN = 3
MAX_SINGLE_USER_SKILL_CHARS = 6000
MAX_TOTAL_USER_SKILL_CHARS = 12000

DEFAULT_ENABLED_SKILLS: Dict[str, Set[str]] = {
    "personal": {
        "using-superpowers",
        "output-formatting",
        "writing-skills",
    },
    "coding": {
        "using-superpowers",
        "project-familiarization",
        "dispatching-parallel-agents",
        "subagent-driven-development",
        "systematic-debugging",
        "test-driven-development",
        "verification-before-completion",
        "requesting-code-review",
        "writing-skills",
    },
}

SKILL_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "quick-code",
        "name": "Quick Code",
        "description": "Fast implementation with project context and verification.",
        "agentTypes": ["coding"],
        "skillIds": [
            "using-superpowers",
            "project-familiarization",
            "test-driven-development",
            "verification-before-completion",
        ],
    },
    {
        "id": "debug-fix",
        "name": "Debug Fix",
        "description": "Systematic bug diagnosis, test guidance, and verification.",
        "agentTypes": ["coding"],
        "skillIds": [
            "using-superpowers",
            "systematic-debugging",
            "test-driven-development",
            "verification-before-completion",
        ],
    },
    {
        "id": "code-review",
        "name": "Code Review",
        "description": "Review-oriented workflow with feedback handling and verification.",
        "agentTypes": ["coding"],
        "skillIds": [
            "requesting-code-review",
            "receiving-code-review",
            "verification-before-completion",
        ],
    },
    {
        "id": "multi-agent-build",
        "name": "Multi-Agent Build",
        "description": "Project exploration plus parallel worker orchestration.",
        "agentTypes": ["coding"],
        "skillIds": [
            "using-superpowers",
            "project-familiarization",
            "dispatching-parallel-agents",
            "subagent-driven-development",
            "verification-before-completion",
        ],
    },
    {
        "id": "personal-daily",
        "name": "Personal Daily",
        "description": "Personal task handling with concise output and learned preferences.",
        "agentTypes": ["personal"],
        "skillIds": [
            "using-superpowers",
            "output-formatting",
        ],
    },
]

SKILL_CATEGORY_BY_ID: Dict[str, str] = {
    "using-superpowers": "core",
    "project-familiarization": "explore-plan",
    "brainstorming": "explore-plan",
    "writing-plans": "explore-plan",
    "executing-plans": "explore-plan",
    "systematic-debugging": "build-debug",
    "test-driven-development": "quality-review",
    "verification-before-completion": "quality-review",
    "requesting-code-review": "quality-review",
    "receiving-code-review": "quality-review",
    "dispatching-parallel-agents": "multi-agent",
    "subagent-driven-development": "multi-agent",
    "using-git-worktrees": "workspace-release",
    "finishing-a-development-branch": "workspace-release",
    "output-formatting": "writing",
    "writing-skills": "writing",
}

SKILL_REASON_BY_ID: Dict[str, str] = {
    "using-superpowers": "Task can benefit from the local skill workflow.",
    "output-formatting": "Personal Agent keeps responses concise and structured.",
    "project-familiarization": "Task asks to understand or work inside the current project.",
    "brainstorming": "Task looks like early design or implementation planning.",
    "writing-plans": "Task benefits from an explicit implementation plan.",
    "executing-plans": "Task asks to execute an existing plan.",
    "systematic-debugging": "Task looks like debugging or bug fixing.",
    "test-driven-development": "Task mentions tests or code changes that should be test-guided.",
    "verification-before-completion": "Coding work should finish with verification.",
    "requesting-code-review": "Task asks for code review or review-style checking.",
    "receiving-code-review": "Task asks to address review feedback.",
    "dispatching-parallel-agents": "Task may benefit from parallel exploration or worker dispatch.",
    "subagent-driven-development": "Task may benefit from specialized worker agents.",
    "using-git-worktrees": "Task involves branch or git workflow changes.",
    "finishing-a-development-branch": "Task looks like branch completion or release cleanup.",
    "writing-skills": "User asks to create, update, validate, or publish an Agent Skill.",
}

MATCH_RULES = [
    {
        "patterns": [
            "skill", "skills", "创建skill", "创建 skill", "新skill", "new skill",
            "create skill", "沉淀成 skill", "沉淀为 skill", "下次遇到", "使用规范",
            "技能", "创建技能", "沉淀成技能", "沉淀为技能",
        ],
        "roles": ["code-expert", "desktop-agent", "general-assistant", "quant-analyst"],
        "skills": ["writing-skills"],
    },
    {
        "patterns": ["实现", "开发", "构建", "添加功能", "新功能", "写一个", "创建",
                     "implement", "develop", "build", "create", "add feature",
                     "编写", "写个", "做个", "开发一个"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "brainstorming", "writing-plans"],
    },
    {
        "patterns": ["bug", "修复", "调试", "报错", "错误", "fix", "debug",
                     "troubleshoot", "broken", "not working"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "systematic-debugging", "test-driven-development"],
    },
    {
        "patterns": ["重构", "优化", "改进", "refactor", "optimize", "improve",
                     "cleanup", "clean up"],
        "roles": ["code-expert"],
        "skills": ["using-superpowers", "test-driven-development", "verification-before-completion"],
    },
    {
        "patterns": ["测试", "test", "unit test", "写测试", "TDD"],
        "roles": ["code-expert"],
        "skills": ["test-driven-development"],
    },
    {
        "patterns": ["审查", "review", "code review", "检查代码"],
        "roles": ["code-expert"],
        "skills": ["requesting-code-review"],
    },
    {
        "patterns": ["git", "分支", "branch", "合并", "merge", "commit", "push", "pull"],
        "roles": ["code-expert"],
        "skills": ["using-git-worktrees"],
    },
    {
        "patterns": ["计划", "方案", "plan", "roadmap", "怎么实现"],
        "roles": ["code-expert"],
        "skills": ["writing-plans"],
    },
    {
        "patterns": ["并行", "同时", "parallel", "并发", "多个任务"],
        "roles": ["code-expert"],
        "skills": ["dispatching-parallel-agents", "subagent-driven-development"],
    },
    {
        "patterns": ["完成", "收尾", "finish", "done", "finalize", "changelog",
                     "release notes", "发布", "合并到主干", "merge to main"],
        "roles": ["code-expert"],
        "skills": ["finishing-a-development-branch", "verification-before-completion"],
    },
    {
        "patterns": ["审查反馈", "review feedback", "根据评审", "按照建议",
                     "address review", "PR feedback", "fix review", "code review feedback"],
        "roles": ["code-expert"],
        "skills": ["receiving-code-review"],
    },
    {
        "patterns": ["按计划", "执行计划", "run the plan", "start implementing",
                     "execute plan", "implement the plan"],
        "roles": ["code-expert"],
        "skills": ["executing-plans", "subagent-driven-development"],
    },
    {
        "patterns": ["熟悉", "了解", "familiarize", "understand the project",
                     "explore the codebase", "项目概览", "overview",
                     "介绍一下项目", "这个项目", "代码结构", "explore the project",
                     "understand the codebase", "familiarize yourself"],
        "roles": ["code-expert", "desktop-agent"],
        "skills": ["project-familiarization", "dispatching-parallel-agents"],
    },
]

SKILL_PRIORITY = [
    "using-superpowers",
    "output-formatting",
    "writing-skills",
    "writing-plans",
    "executing-plans",
    "systematic-debugging",
    "test-driven-development",
    "verification-before-completion",
    "subagent-driven-development",
    "dispatching-parallel-agents",
    "requesting-code-review",
    "receiving-code-review",
    "finishing-a-development-branch",
    "using-git-worktrees",
]

STOP_WORDS = {
    "the", "and", "for", "with", "when", "use", "uses", "using", "this", "that",
    "skill", "skills", "agent", "task", "tasks", "user", "your", "you", "from",
    "into", "should", "will", "can", "need", "needs", "help", "create",
}


def _split_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content.strip()
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content.strip()
    raw = content[3:end].strip()
    body = content[end + 4:].strip()
    try:
        data = yaml.safe_load(raw) if raw else {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def _tokenize(text: str) -> Set[str]:
    tokens: Set[str] = set()
    for token in re.findall(r"[a-zA-Z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", text.lower()):
        cleaned = token.strip("_-")
        if cleaned and cleaned not in STOP_WORDS:
            tokens.add(cleaned)
    return tokens


class SkillManager:
    """Manage bundled, legacy personal, and user-authored Agent Skills."""

    _skills_cache: Optional[Dict[str, Dict[str, Any]]] = None
    _personal_skills_cache: Optional[Dict[str, Dict[str, Any]]] = None
    _user_skills_cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def _normalize_agent_type(cls, agent_type: Optional[str] = None, role_id: Optional[str] = None) -> str:
        if agent_type in AGENT_TYPES:
            return agent_type
        if role_id == "code-expert":
            return "coding"
        return "personal"

    @classmethod
    def _personal_skills_dir(cls) -> Path:
        return agents_dir() / "personal" / PERSONAL_WORKSPACE_DIRNAME / "skills"

    @classmethod
    def _parse_skill_md(cls, path: Path, *, skill_id: str = "", source: str = "superpowers") -> Optional[Dict[str, Any]]:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        frontmatter, body = _split_frontmatter(content)
        name = str(frontmatter.get("name") or path.parent.name).strip()
        description = str(frontmatter.get("description") or "").strip()
        if not description:
            for line in body.splitlines():
                text = line.strip().lstrip("#").strip()
                if text:
                    description = text[:180]
                    break
        return {
            "id": skill_id or name,
            "name": name,
            "description": description,
            "body": body,
            "path": str(path),
            "source": source,
            "frontmatter": frontmatter,
            "status": "published",
        }

    @classmethod
    def _parse_personal_skill_md(cls, path: Path) -> Optional[Dict[str, Any]]:
        parsed = cls._parse_skill_md(path, skill_id=f"{PERSONAL_SKILL_PREFIX}{path.stem}", source="personal")
        if not parsed:
            return None
        parsed["category"] = "personal"
        parsed["status"] = "published"
        return parsed

    @classmethod
    def load_skills(cls) -> Dict[str, Dict[str, Any]]:
        if cls._skills_cache is not None:
            return cls._skills_cache

        skills: Dict[str, Dict[str, Any]] = {}
        if SKILL_DIR.exists():
            for skill_dir in SKILL_DIR.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    parsed = cls._parse_skill_md(skill_md, skill_id=skill_dir.name, source="superpowers")
                    if parsed:
                        skills[parsed["id"]] = parsed

        cls._skills_cache = skills
        return skills

    @classmethod
    def load_personal_skills(cls) -> Dict[str, Dict[str, Any]]:
        if cls._personal_skills_cache is not None:
            return cls._personal_skills_cache

        skills: Dict[str, Dict[str, Any]] = {}
        skills_dir = cls._personal_skills_dir()
        if skills_dir.exists():
            for skill_md in sorted(skills_dir.glob("*.md")):
                parsed = cls._parse_personal_skill_md(skill_md)
                if parsed:
                    skills[parsed["id"]] = parsed

        cls._personal_skills_cache = skills
        return skills

    @classmethod
    def load_user_skills(cls) -> Dict[str, Dict[str, Any]]:
        if cls._user_skills_cache is not None:
            return cls._user_skills_cache

        try:
            from app.skill_authoring import USER_SKILLS_DIR, list_published_entries
        except Exception:
            cls._user_skills_cache = {}
            return {}

        registry_entries = list_published_entries(include_archived=False)
        skills: Dict[str, Dict[str, Any]] = {}
        if USER_SKILLS_DIR.exists():
            for skill_dir in sorted(USER_SKILLS_DIR.iterdir()):
                if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                    continue
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                parsed = cls._parse_skill_md(skill_md, skill_id=f"{USER_SKILL_PREFIX}{skill_dir.name}", source="user")
                if not parsed:
                    continue
                entry = registry_entries.get(parsed["id"], {})
                if entry.get("status") == "archived":
                    continue
                parsed.update({
                    "status": entry.get("status", "published"),
                    "scopes": entry.get("scopes", ["personal"]),
                    "enabledByAgent": entry.get("enabledByAgent", {"personal": True, "coding": False}),
                    "version": entry.get("version", "1.0.0"),
                    "validation": entry.get("validation", {}),
                    "category": "user",
                })
                skills[parsed["id"]] = parsed

        cls._user_skills_cache = skills
        return skills

    @classmethod
    def reload_skills(cls) -> None:
        cls._skills_cache = None
        cls._personal_skills_cache = None
        cls._user_skills_cache = None

    @classmethod
    def _all_skills(cls) -> Dict[str, Dict[str, Any]]:
        return {
            **cls.load_skills(),
            **cls.load_personal_skills(),
            **cls.load_user_skills(),
        }

    @classmethod
    def list_skills(cls) -> List[Dict[str, str]]:
        return [
            {"id": skill_id, "name": s["name"], "description": s["description"]}
            for skill_id, s in cls._all_skills().items()
        ]

    @classmethod
    def _known_skill_ids(cls) -> Set[str]:
        return set(cls._all_skills())

    @classmethod
    def _default_enabled_for(cls, skill_id: str, agent_type: str) -> bool:
        if skill_id.startswith(USER_SKILL_PREFIX):
            skill = cls.load_user_skills().get(skill_id, {})
            enabled = skill.get("enabledByAgent") or {}
            return bool(enabled.get(agent_type, False))
        if skill_id.startswith(PERSONAL_SKILL_PREFIX):
            return agent_type == "personal"
        return skill_id in DEFAULT_ENABLED_SKILLS.get(agent_type, set())

    @classmethod
    def _load_stored_preferences(cls) -> Dict[str, Dict[str, bool]]:
        if not SKILL_PREFS_PATH.exists():
            return {agent: {} for agent in AGENT_TYPES}
        try:
            raw = json.loads(SKILL_PREFS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {agent: {} for agent in AGENT_TYPES}

        preferences: Dict[str, Dict[str, bool]] = {agent: {} for agent in AGENT_TYPES}
        known = cls._known_skill_ids()
        if not isinstance(raw, dict):
            return preferences
        for agent in AGENT_TYPES:
            values = raw.get(agent, {})
            if not isinstance(values, dict):
                continue
            for skill_id, enabled in values.items():
                if skill_id in known and isinstance(enabled, bool):
                    preferences[agent][skill_id] = enabled
        return preferences

    @classmethod
    def effective_preferences(cls) -> Dict[str, Dict[str, bool]]:
        stored = cls._load_stored_preferences()
        known = sorted(cls._known_skill_ids())
        return {
            agent: {
                skill_id: stored[agent].get(skill_id, cls._default_enabled_for(skill_id, agent))
                for skill_id in known
            }
            for agent in AGENT_TYPES
        }

    @classmethod
    def default_preferences(cls) -> Dict[str, Dict[str, bool]]:
        known = sorted(cls._known_skill_ids())
        return {
            agent: {skill_id: cls._default_enabled_for(skill_id, agent) for skill_id in known}
            for agent in AGENT_TYPES
        }

    @classmethod
    def update_preferences(cls, preferences: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        known = cls._known_skill_ids()
        existing = cls._load_stored_preferences()
        ignored: List[str] = []

        for agent in AGENT_TYPES:
            values = preferences.get(agent, {})
            if not isinstance(values, dict):
                continue
            for skill_id, enabled in values.items():
                if skill_id not in known:
                    ignored.append(skill_id)
                    continue
                if isinstance(enabled, bool):
                    existing[agent][skill_id] = enabled

        try:
            SKILL_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SKILL_PREFS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Failed to save skill preferences: {exc}") from exc

        return {
            "preferences": cls.effective_preferences(),
            "ignored": sorted(set(ignored)),
        }

    @classmethod
    def is_skill_enabled(cls, skill_id: str, agent_type: Optional[str] = None, role_id: Optional[str] = None) -> bool:
        agent = cls._normalize_agent_type(agent_type, role_id)
        return cls.effective_preferences().get(agent, {}).get(
            skill_id,
            cls._default_enabled_for(skill_id, agent),
        )

    @classmethod
    def _catalog_item(
        cls,
        *,
        skill_id: str,
        skill: Dict[str, Any],
        source: str,
        preferences: Dict[str, Dict[str, bool]],
        defaults: Dict[str, Dict[str, bool]],
    ) -> Dict[str, Any]:
        recommended_for = [
            agent for agent in AGENT_TYPES
            if defaults[agent].get(skill_id, False)
        ]
        category = skill.get("category") or SKILL_CATEGORY_BY_ID.get(skill_id, source if source in {"personal", "user"} else "other")
        return {
            "id": skill_id,
            "name": skill.get("name", skill_id),
            "description": skill.get("description", ""),
            "source": source,
            "enabledByAgent": {
                "personal": preferences["personal"].get(skill_id, False),
                "coding": preferences["coding"].get(skill_id, False),
            },
            "recommendedFor": recommended_for,
            "category": category,
            "trustLevel": "local",
            "status": skill.get("status", "published"),
            "scopes": skill.get("scopes", recommended_for),
            "version": skill.get("version", ""),
            "validation": skill.get("validation", {}),
        }

    @classmethod
    def list_skill_catalog(cls) -> Dict[str, Any]:
        preferences = cls.effective_preferences()
        defaults = cls.default_preferences()
        catalog: List[Dict[str, Any]] = []

        for skill_id, skill in sorted(cls.load_skills().items()):
            catalog.append(cls._catalog_item(
                skill_id=skill_id,
                skill=skill,
                source="superpowers",
                preferences=preferences,
                defaults=defaults,
            ))

        for skill_id, skill in sorted(cls.load_personal_skills().items()):
            catalog.append(cls._catalog_item(
                skill_id=skill_id,
                skill=skill,
                source="personal",
                preferences=preferences,
                defaults=defaults,
            ))

        for skill_id, skill in sorted(cls.load_user_skills().items()):
            catalog.append(cls._catalog_item(
                skill_id=skill_id,
                skill=skill,
                source="user",
                preferences=preferences,
                defaults=defaults,
            ))

        return {
            "skills": catalog,
            "preferences": preferences,
            "defaults": defaults,
            "presets": cls.list_presets(),
        }

    @classmethod
    def list_presets(cls) -> List[Dict[str, Any]]:
        known = cls._known_skill_ids()
        presets: List[Dict[str, Any]] = []
        for preset in SKILL_PRESETS:
            presets.append({
                **preset,
                "skillIds": [
                    skill_id for skill_id in preset.get("skillIds", [])
                    if skill_id in known
                ],
            })
        return presets

    @classmethod
    def _skill_trace_item(cls, skill_id: str, reason: str) -> Optional[Dict[str, Any]]:
        skill = cls._all_skills().get(skill_id)
        if skill is None:
            return None
        source = skill.get("source", "superpowers")
        return {
            "id": skill_id,
            "name": skill.get("name", skill_id),
            "category": skill.get("category") or SKILL_CATEGORY_BY_ID.get(
                skill_id,
                "personal" if source == "personal" else "user" if source == "user" else "other",
            ),
            "source": source,
            "reason": reason,
        }

    @classmethod
    def _add_candidate(
        cls,
        candidates: Dict[str, Set[str]],
        skill_id: str,
        reason: Optional[str] = None,
    ) -> None:
        candidates.setdefault(skill_id, set()).add(
            reason or SKILL_REASON_BY_ID.get(skill_id, "Matched the current task.")
        )

    @classmethod
    def _collect_rule_candidates(
        cls,
        user_message: str,
        role_id: str,
        has_project: bool,
    ) -> Dict[str, Set[str]]:
        candidates: Dict[str, Set[str]] = {}
        msg_lower = user_message.lower()

        for rule in MATCH_RULES:
            if rule["roles"] and role_id not in rule["roles"]:
                continue
            if any(pattern.lower() in msg_lower for pattern in rule["patterns"]):
                for skill_id in rule["skills"]:
                    cls._add_candidate(candidates, skill_id)

        if has_project and role_id in ("code-expert",):
            cls._add_candidate(candidates, "using-superpowers", "A project is open for Coding Agent work.")
            cls._add_candidate(candidates, "project-familiarization", "A project is open, so project context can improve execution.")
        if role_id in ("code-expert",):
            cls._add_candidate(candidates, "verification-before-completion", "Coding Agent uses verification before completion.")
        if role_id in ("desktop-agent", "general-assistant", "quant-analyst"):
            cls._add_candidate(candidates, "using-superpowers", "Personal Agent can route to relevant local skills.")

        if role_id in ("desktop-agent", "general-assistant", "quant-analyst") and "output-formatting" in cls.load_skills():
            cls._add_candidate(candidates, "output-formatting", "Output formatting is available for concise responses.")

        return candidates

    @classmethod
    def _score_user_skill(cls, skill_id: str, skill: Dict[str, Any], msg_lower: str, msg_tokens: Set[str]) -> int:
        name = str(skill.get("name") or skill_id).lower()
        description = str(skill.get("description") or "").lower()
        aliases = {skill_id.lower(), name, name.replace("-", " "), name.replace("_", " ")}
        if any(alias and alias in msg_lower for alias in aliases):
            return 100

        search_text = " ".join([
            name,
            description,
            " ".join(str(v) for v in (skill.get("frontmatter", {}).get("metadata") or {}).values() if isinstance(v, (str, int, float))),
        ])
        skill_tokens = _tokenize(search_text)
        overlap = len(skill_tokens & msg_tokens)
        if overlap >= 2:
            return overlap
        if overlap == 1 and any(token in description for token in msg_tokens):
            return 1
        return 0

    @classmethod
    def _collect_personal_and_user_candidates(
        cls,
        user_message: str,
        agent_type: str,
    ) -> Dict[str, Set[str]]:
        candidates: Dict[str, Set[str]] = {}
        msg_lower = user_message.lower()
        msg_tokens = _tokenize(user_message)
        scored: List[tuple[int, str, Dict[str, Any]]] = []

        for skill_id, skill in {**cls.load_personal_skills(), **cls.load_user_skills()}.items():
            if skill_id.startswith(USER_SKILL_PREFIX):
                scopes = set(skill.get("scopes") or AGENT_TYPES)
                if agent_type not in scopes:
                    continue
            elif agent_type != "personal":
                continue
            score = cls._score_user_skill(skill_id, skill, msg_lower, msg_tokens)
            if score > 0:
                scored.append((score, skill_id, skill))

        for score, skill_id, skill in sorted(scored, key=lambda x: (-x[0], x[1]))[:MAX_USER_SKILLS_PER_TURN]:
            reason = "Explicitly mentioned by name." if score >= 100 else "Matched user Skill description or trigger keywords."
            candidates.setdefault(skill_id, set()).add(reason)
        return candidates

    @classmethod
    def explain_match_skills(
        cls,
        user_message: str,
        role_id: str,
        has_project: bool,
        agent_type: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        resolved_agent = cls._normalize_agent_type(agent_type, role_id)
        known = cls._known_skill_ids()
        candidates = {
            skill_id: reasons
            for skill_id, reasons in cls._collect_rule_candidates(user_message, role_id, has_project).items()
            if skill_id in known
        }
        for skill_id, reasons in cls._collect_personal_and_user_candidates(user_message, resolved_agent).items():
            if skill_id in known:
                candidates.setdefault(skill_id, set()).update(reasons)

        priority_index = {name: i for i, name in enumerate(SKILL_PRIORITY)}
        ordered_ids = sorted(candidates, key=lambda name: (priority_index.get(name, 999), name))

        enabled_items: List[Dict[str, Any]] = []
        disabled_items: List[Dict[str, Any]] = []
        for skill_id in ordered_ids:
            reason = "; ".join(sorted(candidates[skill_id])[:2])
            item = cls._skill_trace_item(skill_id, reason)
            if item is None:
                continue
            if cls.is_skill_enabled(skill_id, resolved_agent, role_id):
                enabled_items.append(item)
            else:
                disabled_items.append(item)

        return {
            "skills": enabled_items,
            "disabled_matches": disabled_items,
        }

    @classmethod
    def get_skill(cls, name: str) -> Optional[str]:
        skill = cls._all_skills().get(name)
        if not skill:
            return None
        path = Path(skill.get("path", ""))
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8")
                return content
        except (OSError, UnicodeDecodeError):
            pass
        return f"---\nname: {skill['name']}\ndescription: {skill['description']}\n---\n\n{skill['body']}"

    @classmethod
    def get_skill_body(cls, name: str) -> Optional[str]:
        skill = cls._all_skills().get(name)
        return skill["body"] if skill else None

    @classmethod
    def read_skill_record(cls, name: str) -> Optional[Dict[str, Any]]:
        skill = cls._all_skills().get(name)
        if not skill:
            return None
        content = cls.get_skill(name)
        if content is None:
            return None
        return {
            **skill,
            "id": name,
            "skill_id": name,
            "content": content,
        }

    @classmethod
    def match_skills(
        cls,
        user_message: str,
        role_id: str,
        has_project: bool,
        agent_type: Optional[str] = None,
    ) -> List[str]:
        trace = cls.explain_match_skills(user_message, role_id, has_project, agent_type=agent_type)
        return [skill["id"] for skill in trace["skills"]]

    @classmethod
    def build_skill_prompt(cls, skill_names: List[str]) -> str:
        parts: List[str] = []
        user_skill_chars = 0
        for name in skill_names:
            content = cls.get_skill(name)
            if not content:
                continue
            if name.startswith((PERSONAL_SKILL_PREFIX, USER_SKILL_PREFIX)):
                remaining = MAX_TOTAL_USER_SKILL_CHARS - user_skill_chars
                if remaining <= 0:
                    continue
                limit = min(MAX_SINGLE_USER_SKILL_CHARS, remaining)
                if len(content) > limit:
                    content = content[:limit] + "\n\n[Skill content truncated for context budget.]"
                user_skill_chars += len(content)
            parts.append(f"\n## Skill: {name}\n{content}\n")
        return "\n".join(parts)
