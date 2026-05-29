"""User-authored persistent Specialist Agents.

Specialists are local runtime Agent definitions. They live under the user's
AGENTS runtime directory and are intentionally separate from repo templates.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.runtime_paths import agents_dir, runtime_file
from app.security import is_relative_to


AGENT_TYPE_PREFIX = "specialist:"
BASE_KINDS = frozenset({"advisory", "coding", "desktop"})
AUTO_DELEGATE_VALUES = frozenset({"off", "suggest", "auto"})
THINKING_VALUES = frozenset({"low", "medium", "high"})
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")

REGISTRY_PATH = runtime_file("data", "specialist_agent_registry.json")
AUDIT_PATH = runtime_file("data", "specialist_agent_audit.jsonl")

DEFAULT_TOOLS_BY_BASE_KIND: Dict[str, List[str]] = {
    "advisory": ["web_search", "web_fetch", "knowledge_search", "knowledge_list"],
    "coding": [
        "repo_map", "code_search", "file_outline",
        "file_read", "file_list", "file_search",
        "git_status", "git_diff", "web_search", "web_fetch",
    ],
    "desktop": [
        "web_search", "web_fetch", "knowledge_search", "knowledge_list",
        "screenshot", "automation_observe", "browser_navigate", "browser_screenshot",
    ],
}

RISKY_TOOLS = frozenset({
    "shell_execute", "shell_start",
    "file_write", "file_patch", "file_delete",
    "git_commit", "git_push", "git_pull", "git_branch", "git_clone",
    "browser_click", "browser_type", "browser_evaluate", "browser_close",
    "mouse_click", "mouse_move", "type_text", "press_key", "scroll",
    "app_open", "app_click", "app_type",
    "automation_click", "automation_type", "automation_key", "automation_scroll", "automation_replay",
})

HIGH_RISK_PATTERNS = [
    re.compile(r"(?i)\b(ignore|disable|bypass|turn off)\b.{0,40}\b(guardrail|safety|approval|policy)\b"),
    re.compile(r"(?i)\b(delete everything|wipe|format\s+[a-z]:|reset --hard|clean -fd|force push)\b"),
    re.compile(r"(?i)\b(secret|token|api[_-]?key|password)\b.{0,60}\b(print|expose|dump|send)\b"),
]


class SpecialistAuthoringError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_slug(value: str) -> str:
    slug = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:64].strip("-") or "specialist-agent"


def agent_type_for_slug(slug: str) -> str:
    return f"{AGENT_TYPE_PREFIX}{slug}"


def slug_from_agent_type(agent_type: str) -> str:
    value = str(agent_type or "")
    return value[len(AGENT_TYPE_PREFIX):] if value.startswith(AGENT_TYPE_PREFIX) else value


def is_specialist_agent_type(agent_type: str) -> bool:
    return str(agent_type or "").startswith(AGENT_TYPE_PREFIX)


def _agents_root() -> Path:
    try:
        from app.agents.manager import AgentManager

        if AgentManager.AGENTS_DIR is not None:
            return AgentManager.AGENTS_DIR
    except Exception:
        pass
    return agents_dir()


def _root() -> Path:
    path = _agents_root() / "specialists"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _drafts_dir() -> Path:
    path = _root() / ".drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _archive_dir() -> Path:
    path = _root() / ".archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_specialist_path(*parts: str) -> Path:
    base = _root().resolve()
    path = _root().joinpath(*parts).resolve()
    if not is_relative_to(path, base):
        raise SpecialistAuthoringError("Path escapes AGENTS/specialists.")
    return path


def _load_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"specialists": {}, "drafts": {}}
    try:
        raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"specialists": {}, "drafts": {}}
    if not isinstance(raw, dict):
        return {"specialists": {}, "drafts": {}}
    specialists = raw.setdefault("specialists", {})
    drafts = raw.setdefault("drafts", {})
    if not isinstance(specialists, dict):
        raw["specialists"] = {}
    if not isinstance(drafts, dict):
        raw["drafts"] = {}
    return raw


def _save_registry(registry: Dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def _audit(action: str, payload: Dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), "action": action, **payload}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _clean_text(value: Any, max_len: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_len]


def _clean_list(values: Optional[Iterable[Any]], *, max_items: int = 20, max_len: int = 160) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values or []:
        text = _clean_text(value, max_len=max_len)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= max_items:
            break
    return result


def _known_static_tools() -> set[str]:
    try:
        from app.tools import list_static_tool_names

        return set(list_static_tool_names())
    except Exception:
        return set()


def _normalize_allowed_tools(base_kind: str, allowed_tools: Optional[Iterable[Any]]) -> List[str]:
    known = _known_static_tools()
    fallback = DEFAULT_TOOLS_BY_BASE_KIND.get(base_kind, DEFAULT_TOOLS_BY_BASE_KIND["advisory"])
    requested = [str(item or "").strip() for item in (allowed_tools or []) if str(item or "").strip()]
    if not requested:
        requested = fallback
    result: List[str] = []
    seen: set[str] = set()
    for name in requested:
        if name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _validation_issue(level: str, code: str, message: str) -> Dict[str, str]:
    return {"level": level, "code": code, "message": message}


def _build_specialist_payload(
    *,
    slug: str,
    display_name: str,
    description: str,
    instructions: str,
    trigger_examples: Optional[Iterable[Any]] = None,
    routing_keywords: Optional[Iterable[Any]] = None,
    auto_delegate: str = "suggest",
    base_kind: str = "advisory",
    allowed_tools: Optional[Iterable[Any]] = None,
    skill_ids: Optional[Iterable[Any]] = None,
    model_id: str = "",
    thinking_intensity: str = "medium",
) -> Dict[str, Any]:
    normalized_slug = normalize_slug(slug or display_name)
    normalized_base = base_kind if base_kind in BASE_KINDS else "advisory"
    normalized_auto = auto_delegate if auto_delegate in AUTO_DELEGATE_VALUES else "suggest"
    normalized_thinking = thinking_intensity if thinking_intensity in THINKING_VALUES else "medium"
    return {
        "slug": normalized_slug,
        "agent_type": agent_type_for_slug(normalized_slug),
        "display_name": _clean_text(display_name, 80) or normalized_slug,
        "description": _clean_text(description, 300),
        "instructions": str(instructions or "").strip()[:12000],
        "trigger_examples": _clean_list(trigger_examples, max_items=20),
        "routing_keywords": _clean_list(routing_keywords, max_items=40, max_len=80),
        "auto_delegate": normalized_auto,
        "base_kind": normalized_base,
        "allowed_tools": _normalize_allowed_tools(normalized_base, allowed_tools),
        "skill_ids": _clean_list(skill_ids, max_items=20, max_len=120),
        "model_id": _clean_text(model_id, 160),
        "thinking_intensity": normalized_thinking,
    }


def validate_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    risks: List[Dict[str, str]] = []

    slug = str(data.get("slug") or "")
    if not SLUG_RE.match(slug):
        issues.append(_validation_issue("error", "slug", "Slug must use lowercase letters, numbers, and single hyphens."))
    if not str(data.get("display_name") or "").strip():
        issues.append(_validation_issue("error", "display_name", "Display name is required."))
    if not str(data.get("description") or "").strip():
        issues.append(_validation_issue("error", "description", "Description is required."))
    instructions = str(data.get("instructions") or "").strip()
    if not instructions:
        issues.append(_validation_issue("error", "instructions", "Instructions are required."))
    elif len(instructions) < 20:
        warnings.append(_validation_issue("warning", "instructions_short", "Instructions are very short."))
    if data.get("auto_delegate") not in AUTO_DELEGATE_VALUES:
        issues.append(_validation_issue("error", "auto_delegate", "auto_delegate must be off, suggest, or auto."))
    if data.get("base_kind") not in BASE_KINDS:
        issues.append(_validation_issue("error", "base_kind", "base_kind must be advisory, coding, or desktop."))

    known = _known_static_tools()
    for tool_name in data.get("allowed_tools") or []:
        if known and tool_name not in known:
            issues.append(_validation_issue("error", "allowed_tools", f"Unknown tool: {tool_name}"))
    risky_tools = sorted(set(data.get("allowed_tools") or []) & RISKY_TOOLS)
    if risky_tools:
        risks.append(_validation_issue("risk", "risky_tools", "Specialist includes mutation or control tools: " + ", ".join(risky_tools)))
    if data.get("auto_delegate") == "auto" and risky_tools:
        risks.append(_validation_issue("risk", "auto_delegate_risky", "Auto-delegation cannot be safely enabled with risky tools."))
    for pattern in HIGH_RISK_PATTERNS:
        if pattern.search(instructions):
            risks.append(_validation_issue("risk", "high_risk_instruction", "Instructions contain high-risk safety or secret-handling language."))
            break

    return {
        "passed": not issues and not risks,
        "issues": issues,
        "warnings": warnings,
        "risks": risks,
        "slug": slug,
    }


def _write_specialist_files(root: Path, payload: Dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "specialist.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "INSTRUCTIONS.md").write_text(str(payload.get("instructions") or "").rstrip() + "\n", encoding="utf-8")


def save_draft(
    *,
    slug: str = "",
    display_name: str,
    description: str,
    instructions: str,
    trigger_examples: Optional[Iterable[Any]] = None,
    routing_keywords: Optional[Iterable[Any]] = None,
    auto_delegate: str = "suggest",
    base_kind: str = "advisory",
    allowed_tools: Optional[Iterable[Any]] = None,
    skill_ids: Optional[Iterable[Any]] = None,
    model_id: str = "",
    thinking_intensity: str = "medium",
    created_from: str = "conversation",
) -> Dict[str, Any]:
    payload = _build_specialist_payload(
        slug=slug,
        display_name=display_name,
        description=description,
        instructions=instructions,
        trigger_examples=trigger_examples,
        routing_keywords=routing_keywords,
        auto_delegate=auto_delegate,
        base_kind=base_kind,
        allowed_tools=allowed_tools,
        skill_ids=skill_ids,
        model_id=model_id,
        thinking_intensity=thinking_intensity,
    )
    validation = validate_payload(payload)
    if validation["issues"]:
        raise SpecialistAuthoringError("; ".join(issue["message"] for issue in validation["issues"]))

    draft_id = f"{payload['slug']}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    draft_dir = (_drafts_dir() / draft_id).resolve()
    if not is_relative_to(draft_dir, _drafts_dir().resolve()):
        raise SpecialistAuthoringError("Draft path escapes AGENTS/specialists.")
    now = now_iso()
    entry = {
        **payload,
        "id": draft_id,
        "draft_id": draft_id,
        "status": "draft",
        "source": "user",
        "created_from": created_from,
        "path": str(draft_dir),
        "created_at": now,
        "updated_at": now,
        "validation": validation,
    }
    _write_specialist_files(draft_dir, entry)
    registry = _load_registry()
    registry.setdefault("drafts", {})[draft_id] = entry
    _save_registry(registry)
    _audit("draft", {"draft_id": draft_id, "slug": payload["slug"]})
    SpecialistRegistry.reload()
    return entry


def validate_specialist(path_or_id: str) -> Dict[str, Any]:
    registry = _load_registry()
    entry = registry.get("drafts", {}).get(path_or_id) or registry.get("specialists", {}).get(path_or_id)
    if not entry and path_or_id.startswith(AGENT_TYPE_PREFIX):
        entry = registry.get("specialists", {}).get(slug_from_agent_type(path_or_id))
    if not entry:
        path = Path(path_or_id)
        if path.is_dir():
            spec_path = path / "specialist.json"
        else:
            spec_path = path
        try:
            entry = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SpecialistAuthoringError(f"Specialist not found: {path_or_id}") from exc
    validation = validate_payload(entry)
    key = entry.get("draft_id") or entry.get("slug")
    if entry.get("status") == "draft":
        registry.setdefault("drafts", {})[key] = {**entry, "validation": validation, "updated_at": now_iso()}
    elif entry.get("slug"):
        registry.setdefault("specialists", {})[entry["slug"]] = {**entry, "validation": validation, "updated_at": now_iso()}
    _save_registry(registry)
    SpecialistRegistry.reload()
    return validation


def _archive_existing(target_dir: Path, slug: str) -> str:
    if not target_dir.exists():
        return ""
    archive_target = _archive_dir() / f"{slug}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    suffix = 1
    while archive_target.exists():
        archive_target = _archive_dir() / f"{slug}-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{suffix}"
        suffix += 1
    shutil.move(str(target_dir), str(archive_target))
    return str(archive_target)


def publish_draft(draft_id: str, *, allow_risky: bool = False) -> Dict[str, Any]:
    registry = _load_registry()
    draft = registry.get("drafts", {}).get(draft_id)
    if not draft:
        raise SpecialistAuthoringError(f"Draft not found: {draft_id}")
    validation = validate_payload(draft)
    if validation.get("issues"):
        raise SpecialistAuthoringError("Draft has validation errors and cannot be published.")
    if validation.get("risks") and not allow_risky:
        raise SpecialistAuthoringError("Draft has high-risk findings; explicit confirmation is required.")

    slug = draft["slug"]
    target_dir = _safe_specialist_path(slug)
    archive_path = _archive_existing(target_dir, slug)
    source = Path(draft["path"])
    shutil.copytree(source, target_dir)
    shutil.rmtree(source, ignore_errors=True)
    now = now_iso()
    entry = {
        **draft,
        "id": agent_type_for_slug(slug),
        "status": "published",
        "path": str(target_dir),
        "published_at": now,
        "updated_at": now,
        "validation": validation,
        "archive_path": archive_path,
    }
    entry.pop("draft_id", None)
    registry.setdefault("drafts", {}).pop(draft_id, None)
    registry.setdefault("specialists", {})[slug] = entry
    _write_specialist_files(target_dir, entry)
    _save_registry(registry)
    _audit("publish", {"draft_id": draft_id, "slug": slug, "archive_path": archive_path})
    SpecialistRegistry.reload()
    return entry


def update_specialist(slug: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    registry = _load_registry()
    normalized = normalize_slug(slug)
    current = registry.get("specialists", {}).get(normalized)
    if not current or current.get("status") == "archived":
        raise SpecialistAuthoringError(f"Published specialist not found: {slug}")
    merged = {**current, **{k: v for k, v in updates.items() if v is not None}}
    payload = _build_specialist_payload(
        slug=current["slug"],
        display_name=merged.get("display_name", ""),
        description=merged.get("description", ""),
        instructions=merged.get("instructions", ""),
        trigger_examples=merged.get("trigger_examples"),
        routing_keywords=merged.get("routing_keywords"),
        auto_delegate=merged.get("auto_delegate", "suggest"),
        base_kind=merged.get("base_kind", "advisory"),
        allowed_tools=merged.get("allowed_tools"),
        skill_ids=merged.get("skill_ids"),
        model_id=merged.get("model_id", ""),
        thinking_intensity=merged.get("thinking_intensity", "medium"),
    )
    validation = validate_payload(payload)
    if validation["issues"]:
        raise SpecialistAuthoringError("; ".join(issue["message"] for issue in validation["issues"]))
    entry = {
        **current,
        **payload,
        "status": "published",
        "updated_at": now_iso(),
        "validation": validation,
    }
    registry.setdefault("specialists", {})[current["slug"]] = entry
    _write_specialist_files(Path(entry["path"]), entry)
    _save_registry(registry)
    _audit("update", {"slug": current["slug"]})
    SpecialistRegistry.reload()
    return entry


def archive_specialist(slug_or_agent_type: str) -> Dict[str, Any]:
    registry = _load_registry()
    slug = normalize_slug(slug_from_agent_type(slug_or_agent_type))
    entry = registry.get("specialists", {}).get(slug)
    if not entry:
        raise SpecialistAuthoringError(f"Published specialist not found: {slug_or_agent_type}")
    archive_path = _archive_existing(Path(entry.get("path") or _safe_specialist_path(slug)), slug)
    archived = {
        **entry,
        "status": "archived",
        "path": archive_path,
        "archived_at": now_iso(),
        "updated_at": now_iso(),
    }
    registry.setdefault("specialists", {}).pop(slug, None)
    registry.setdefault("archived", {})[slug] = archived
    _save_registry(registry)
    _audit("archive", {"slug": slug, "archive_path": archive_path})
    SpecialistRegistry.reload()
    return archived


def read_specialist(slug_or_agent_type: str) -> Dict[str, Any]:
    slug = normalize_slug(slug_from_agent_type(slug_or_agent_type))
    entry = SpecialistRegistry.get(slug)
    if not entry:
        raise SpecialistAuthoringError(f"Specialist not found: {slug_or_agent_type}")
    return entry


def list_specialists(include_archived: bool = False) -> List[Dict[str, Any]]:
    registry = _load_registry()
    items = list(registry.get("specialists", {}).values())
    if include_archived:
        items.extend(registry.get("archived", {}).values())
    return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)


class SpecialistRegistry:
    """Cached read access for published Specialist Agents."""

    _cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def reload(cls) -> None:
        cls._cache = None

    @classmethod
    def _published(cls) -> Dict[str, Dict[str, Any]]:
        if cls._cache is not None:
            return cls._cache
        registry = _load_registry()
        published: Dict[str, Dict[str, Any]] = {}
        for slug, entry in registry.get("specialists", {}).items():
            if entry.get("status") == "archived":
                continue
            published[slug] = entry
        cls._cache = published
        return published

    @classmethod
    def get(cls, slug_or_agent_type: str) -> Optional[Dict[str, Any]]:
        slug = normalize_slug(slug_from_agent_type(slug_or_agent_type))
        item = cls._published().get(slug)
        return dict(item) if item else None

    @classmethod
    def all(cls) -> List[Dict[str, Any]]:
        return sorted((dict(item) for item in cls._published().values()), key=lambda item: item.get("display_name", ""))

    @classmethod
    def is_known_agent_type(cls, agent_type: str) -> bool:
        return is_specialist_agent_type(agent_type) and cls.get(agent_type) is not None

    @classmethod
    def allowed_tools_for_agent(cls, agent_type: str) -> Optional[frozenset[str]]:
        spec = cls.get(agent_type)
        if not spec:
            return None
        return frozenset(spec.get("allowed_tools") or [])

    @classmethod
    def base_kind_for_agent(cls, agent_type: str) -> str:
        spec = cls.get(agent_type)
        return str((spec or {}).get("base_kind") or "advisory")
