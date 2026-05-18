from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from app.runtime_paths import agents_dir, runtime_file
from app.security import is_relative_to


AGENT_TYPES: tuple[str, str] = ("personal", "coding")
USER_SKILLS_DIR = agents_dir() / "skills"
DRAFTS_DIR = USER_SKILLS_DIR / ".drafts"
ARCHIVE_DIR = USER_SKILLS_DIR / ".archive"
REGISTRY_PATH = runtime_file("data", "skill_registry.json")
AUDIT_PATH = runtime_file("data", "skill_audit.jsonl")

SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SECRET_PATTERNS = [
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"(?i)\bglpat-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
]
HIGH_RISK_PATTERNS = [
    re.compile(r"(?i)\b(ignore|disable|bypass|turn off)\b.{0,40}\b(guardrail|safety|approval|sandbox|policy)\b"),
    re.compile(r"(?i)\b(shell_execute|exec|subprocess|powershell|cmd\.exe|bash)\b.{0,80}\b(user input|untrusted|raw input)\b"),
    re.compile(r"(?i)\b(delete everything|wipe|format\s+[a-z]:|reset --hard|clean -fd|force push)\b"),
]
TRIGGER_HINT_RE = re.compile(r"(?i)\b(use when|when|whenever|for tasks|适用|用于|当|遇到|需要|下次)\b")


class SkillAuthoringError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_skill_name(name: str) -> str:
    candidate = (name or "").strip().lower()
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not candidate:
        candidate = "new-skill"
    return candidate[:64].strip("-") or "new-skill"


def validate_skill_name(name: str) -> Optional[str]:
    if not name:
        return "Skill name is required."
    if len(name) > 64:
        return "Skill name must be 64 characters or fewer."
    if not SKILL_NAME_RE.match(name) or "--" in name:
        return "Skill name must use lowercase letters, numbers, and single hyphens only."
    return None


def _safe_user_skill_path(*parts: str) -> Path:
    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    base = USER_SKILLS_DIR.resolve()
    path = (USER_SKILLS_DIR.joinpath(*parts)).resolve()
    if not is_relative_to(path, base):
        raise SkillAuthoringError("Path escapes AGENTS/skills.")
    return path


def _load_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"skills": {}, "drafts": {}}
    try:
        raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"skills": {}, "drafts": {}}
    if not isinstance(raw, dict):
        return {"skills": {}, "drafts": {}}
    skills = raw.setdefault("skills", {})
    drafts = raw.setdefault("drafts", {})
    if not isinstance(skills, dict):
        raw["skills"] = {}
    if not isinstance(drafts, dict):
        raw["drafts"] = {}
    return raw


def _save_registry(registry: Dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def _audit(action: str, payload: Dict[str, Any]) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": now_iso(), "action": action, **payload}
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def split_frontmatter(content: str) -> tuple[Dict[str, Any], str, Optional[str]]:
    if not content.startswith("---"):
        return {}, content.strip(), None
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content.strip(), "Frontmatter is not closed."
    raw = content[3:end].strip()
    body = content[end + 4:].strip()
    try:
        parsed = yaml.safe_load(raw) if raw else {}
    except yaml.YAMLError as exc:
        return {}, body, f"Invalid YAML frontmatter: {exc}"
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, body, "Frontmatter must be a YAML mapping."
    return parsed, body, None


def build_skill_markdown(
    *,
    name: str,
    description: str,
    body: str,
    compatibility: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    allowed_tools: str = "",
) -> str:
    frontmatter: Dict[str, Any] = {
        "name": name,
        "description": description.strip(),
    }
    if compatibility.strip():
        frontmatter["compatibility"] = compatibility.strip()
    if metadata:
        frontmatter["metadata"] = metadata
    if allowed_tools.strip():
        frontmatter["allowed-tools"] = allowed_tools.strip()
    return "---\n" + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip() + "\n---\n\n" + body.strip() + "\n"


def _normalize_scopes(scopes: Optional[Iterable[str]]) -> List[str]:
    values = [s for s in (scopes or []) if s in AGENT_TYPES]
    return sorted(set(values)) or ["personal"]


def _enabled_by_agent(enable_for: Optional[Iterable[str]], scopes: Iterable[str]) -> Dict[str, bool]:
    enabled = set(enable_for or [])
    if not enabled:
        enabled = {"personal"}
    scopes_set = set(scopes)
    return {agent: agent in enabled and agent in scopes_set for agent in AGENT_TYPES}


def _write_resource(root: Path, resource: Dict[str, Any]) -> str:
    raw_path = str(resource.get("path") or "").replace("\\", "/").strip("/")
    content = str(resource.get("content") or "")
    if not raw_path:
        raise SkillAuthoringError("Resource path is required.")
    first = raw_path.split("/", 1)[0]
    if first not in {"references", "assets", "scripts"}:
        raise SkillAuthoringError("Resource path must start with references/, assets/, or scripts/.")
    target = (root / raw_path).resolve()
    if not is_relative_to(target, root.resolve()):
        raise SkillAuthoringError("Resource path escapes the skill directory.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return raw_path


def save_draft(
    *,
    name: str,
    description: str,
    body: str,
    scopes: Optional[Iterable[str]] = None,
    resources: Optional[List[Dict[str, Any]]] = None,
    compatibility: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    allowed_tools: str = "",
    created_from: str = "conversation",
) -> Dict[str, Any]:
    skill_name = normalize_skill_name(name)
    name_error = validate_skill_name(skill_name)
    if name_error:
        raise SkillAuthoringError(name_error)
    if not description.strip():
        raise SkillAuthoringError("Skill description is required.")

    draft_id = f"{skill_name}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    draft_dir = _safe_user_skill_path(".drafts", draft_id)
    draft_dir.mkdir(parents=True, exist_ok=False)
    scopes_list = _normalize_scopes(scopes)

    content = body.strip()
    fm, body_without_fm, fm_error = split_frontmatter(content)
    if not fm_error and fm:
        content = build_skill_markdown(
            name=skill_name,
            description=description.strip() or str(fm.get("description") or ""),
            body=body_without_fm,
            compatibility=compatibility or str(fm.get("compatibility") or ""),
            metadata=metadata or fm.get("metadata") if isinstance(fm.get("metadata"), dict) else metadata,
            allowed_tools=allowed_tools or str(fm.get("allowed-tools") or ""),
        )
    else:
        content = build_skill_markdown(
            name=skill_name,
            description=description,
            body=body,
            compatibility=compatibility,
            metadata=metadata,
            allowed_tools=allowed_tools,
        )

    skill_md = draft_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    written_resources: List[str] = []
    for resource in resources or []:
        written_resources.append(_write_resource(draft_dir, resource))

    validation = validate_skill_path(draft_dir)
    registry = _load_registry()
    entry = {
        "id": draft_id,
        "draft_id": draft_id,
        "skill_id": f"user:{skill_name}",
        "name": skill_name,
        "description": description.strip(),
        "status": "draft",
        "source": "user",
        "created_from": created_from,
        "scopes": scopes_list,
        "enabledByAgent": _enabled_by_agent(["personal"], scopes_list),
        "path": str(draft_dir),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "resources": written_resources,
        "validation": validation,
    }
    registry.setdefault("drafts", {})[draft_id] = entry
    _save_registry(registry)
    _audit("draft", {"draft_id": draft_id, "skill_id": entry["skill_id"], "path": str(draft_dir)})
    return entry


def update_draft(
    draft_id: str,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    body: Optional[str] = None,
    scopes: Optional[Iterable[str]] = None,
    resources: Optional[List[Dict[str, Any]]] = None,
    compatibility: str = "",
    allowed_tools: str = "",
) -> Dict[str, Any]:
    registry = _load_registry()
    entry = registry.get("drafts", {}).get(draft_id)
    if not entry:
        raise SkillAuthoringError(f"Draft not found: {draft_id}")

    draft_dir = Path(entry["path"])
    skill_md = draft_dir / "SKILL.md"
    try:
        existing = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillAuthoringError(f"Could not read draft: {exc}") from exc
    fm, existing_body, _ = split_frontmatter(existing)

    next_name = normalize_skill_name(name or entry.get("name") or fm.get("name") or "")
    name_error = validate_skill_name(next_name)
    if name_error:
        raise SkillAuthoringError(name_error)
    next_description = (description if description is not None else entry.get("description") or fm.get("description") or "").strip()
    if not next_description:
        raise SkillAuthoringError("Skill description is required.")
    next_body = body if body is not None else existing_body

    content = build_skill_markdown(
        name=next_name,
        description=next_description,
        body=next_body,
        compatibility=compatibility or str(fm.get("compatibility") or ""),
        metadata=fm.get("metadata") if isinstance(fm.get("metadata"), dict) else None,
        allowed_tools=allowed_tools or str(fm.get("allowed-tools") or ""),
    )
    skill_md.write_text(content, encoding="utf-8")
    written_resources = list(entry.get("resources") or [])
    for resource in resources or []:
        written_resources.append(_write_resource(draft_dir, resource))

    scopes_list = _normalize_scopes(scopes if scopes is not None else entry.get("scopes"))
    validation = validate_skill_path(draft_dir)
    updated = {
        **entry,
        "name": next_name,
        "description": next_description,
        "skill_id": f"user:{next_name}",
        "scopes": scopes_list,
        "resources": sorted(set(written_resources)),
        "validation": validation,
        "updated_at": now_iso(),
    }
    registry.setdefault("drafts", {})[draft_id] = updated
    _save_registry(registry)
    _audit("draft_update", {"draft_id": draft_id, "skill_id": updated["skill_id"]})
    return updated


def _issue(level: str, code: str, message: str) -> Dict[str, str]:
    return {"level": level, "code": code, "message": message}


def validate_skill_path(path: Path) -> Dict[str, Any]:
    root = path if path.is_dir() else path.parent
    skill_md = root / "SKILL.md" if root.is_dir() else path
    issues: List[Dict[str, str]] = []
    risks: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    if not skill_md.exists():
        issues.append(_issue("error", "missing_skill_md", "SKILL.md is required."))
        return {"passed": False, "issues": issues, "warnings": warnings, "risks": risks}

    try:
        content = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(_issue("error", "read_failed", f"Could not read SKILL.md: {exc}"))
        return {"passed": False, "issues": issues, "warnings": warnings, "risks": risks}

    fm, body, fm_error = split_frontmatter(content)
    if fm_error:
        issues.append(_issue("error", "frontmatter", fm_error))

    name = str(fm.get("name") or "").strip()
    description = str(fm.get("description") or "").strip()
    name_error = validate_skill_name(name)
    if name_error:
        issues.append(_issue("error", "name", name_error))
    if name and root.name not in {name, ".drafts"} and not root.parent.name == ".drafts":
        issues.append(_issue("error", "directory_name", "Published skill directory name must match frontmatter name."))
    if not description:
        issues.append(_issue("error", "description", "Description is required."))
    elif len(description) > 1024:
        issues.append(_issue("error", "description_length", "Description must be 1024 characters or fewer."))
    elif not TRIGGER_HINT_RE.search(description):
        warnings.append(_issue("warning", "description_trigger", "Description should say when to use the skill."))

    if len(body.splitlines()) > 500:
        warnings.append(_issue("warning", "body_lines", "SKILL.md body is over 500 lines; move details to references/."))
    if int(len(body) / 3.6) > 5000:
        warnings.append(_issue("warning", "body_tokens", "SKILL.md body is likely over 5000 tokens."))

    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            risks.append(_issue("risk", "possible_secret", "SKILL.md appears to contain a secret or credential."))
            break
    for pattern in HIGH_RISK_PATTERNS:
        if pattern.search(content):
            risks.append(_issue("risk", "high_risk_instruction", "SKILL.md contains high-risk safety or command instructions."))
            break

    scripts_dir = root / "scripts"
    if scripts_dir.exists() and any(p.is_file() for p in scripts_dir.rglob("*")):
        risks.append(_issue("risk", "scripts_present", "Skill includes scripts; publishing requires explicit high-risk confirmation."))

    return {
        "passed": not issues and not risks,
        "issues": issues,
        "warnings": warnings,
        "risks": risks,
        "name": name,
        "description": description,
    }


def _resolve_skill_or_draft(path_or_id: str) -> tuple[Optional[Path], Optional[Dict[str, Any]], str]:
    registry = _load_registry()
    if path_or_id in registry.get("drafts", {}):
        entry = registry["drafts"][path_or_id]
        return Path(entry["path"]), entry, "draft"
    if path_or_id in registry.get("skills", {}):
        entry = registry["skills"][path_or_id]
        return Path(entry["path"]), entry, "published"
    if path_or_id.startswith("user:"):
        entry = registry.get("skills", {}).get(path_or_id)
        if entry:
            return Path(entry["path"]), entry, "published"
        name = path_or_id.split(":", 1)[1]
        return _safe_user_skill_path(name), None, "published"
    path = Path(path_or_id)
    return path, None, "path"


def validate_skill(path_or_id: str) -> Dict[str, Any]:
    path, entry, status = _resolve_skill_or_draft(path_or_id)
    if path is None:
        raise SkillAuthoringError(f"Skill not found: {path_or_id}")
    validation = validate_skill_path(path)
    registry = _load_registry()
    if status == "draft" and entry:
        entry["validation"] = validation
        entry["updated_at"] = now_iso()
        registry.setdefault("drafts", {})[entry["draft_id"]] = entry
        _save_registry(registry)
        _audit("validate", {"draft_id": entry["draft_id"], "passed": validation["passed"]})
    elif status == "published" and entry:
        entry["validation"] = validation
        entry["updated_at"] = now_iso()
        registry.setdefault("skills", {})[entry["skill_id"]] = entry
        _save_registry(registry)
        _audit("validate", {"skill_id": entry["skill_id"], "passed": validation["passed"]})
    return validation


def _archive_existing(target_dir: Path, skill_name: str) -> Optional[str]:
    if not target_dir.exists():
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = ARCHIVE_DIR / f"{skill_name}-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    shutil.move(str(target_dir), str(archive_path))
    return str(archive_path)


def publish_draft(
    draft_id: str,
    *,
    enable_for: Optional[Iterable[str]] = None,
    allow_risky: bool = False,
) -> Dict[str, Any]:
    registry = _load_registry()
    draft = registry.get("drafts", {}).get(draft_id)
    if not draft:
        raise SkillAuthoringError(f"Draft not found: {draft_id}")

    draft_dir = Path(draft["path"])
    validation = validate_skill_path(draft_dir)
    if validation.get("issues"):
        raise SkillAuthoringError("Draft has validation errors and cannot be published.")
    if validation.get("risks") and not allow_risky:
        raise SkillAuthoringError("Draft has high-risk findings; explicit high-risk confirmation is required.")

    skill_name = draft["name"]
    target_dir = _safe_user_skill_path(skill_name)
    archive_path = _archive_existing(target_dir, skill_name)
    shutil.copytree(draft_dir, target_dir)
    shutil.rmtree(draft_dir, ignore_errors=True)

    scopes = _normalize_scopes(draft.get("scopes") or ["personal"])
    skill_id = f"user:{skill_name}"
    entry = {
        **draft,
        "id": skill_id,
        "skill_id": skill_id,
        "status": "published",
        "version": str(draft.get("version") or "1.0.0"),
        "path": str(target_dir),
        "scopes": scopes,
        "enabledByAgent": _enabled_by_agent(enable_for, scopes),
        "validation": validation,
        "published_at": now_iso(),
        "updated_at": now_iso(),
        "archive_path": archive_path,
    }
    entry.pop("draft_id", None)
    registry.setdefault("drafts", {}).pop(draft_id, None)
    registry.setdefault("skills", {})[skill_id] = entry
    _save_registry(registry)
    _audit("publish", {"draft_id": draft_id, "skill_id": skill_id, "path": str(target_dir), "archive_path": archive_path})
    _reload_skill_manager()
    return entry


def archive_skill(skill_id: str) -> Dict[str, Any]:
    registry = _load_registry()
    normalized = skill_id if skill_id.startswith("user:") else f"user:{skill_id}"
    entry = registry.get("skills", {}).get(normalized)
    if not entry:
        raise SkillAuthoringError(f"Published user skill not found: {skill_id}")
    path = Path(entry["path"])
    skill_name = entry["name"]
    archive_path = _archive_existing(path, skill_name)
    entry = {
        **entry,
        "status": "archived",
        "enabledByAgent": {agent: False for agent in AGENT_TYPES},
        "archived_at": now_iso(),
        "updated_at": now_iso(),
        "path": archive_path or entry.get("path", ""),
    }
    registry.setdefault("skills", {})[normalized] = entry
    _save_registry(registry)
    _audit("archive", {"skill_id": normalized, "archive_path": archive_path})
    _reload_skill_manager()
    return entry


def list_drafts() -> List[Dict[str, Any]]:
    registry = _load_registry()
    drafts = list(registry.get("drafts", {}).values())
    return sorted(drafts, key=lambda d: d.get("updated_at", ""), reverse=True)


def list_published_entries(include_archived: bool = False) -> Dict[str, Dict[str, Any]]:
    registry = _load_registry()
    entries: Dict[str, Dict[str, Any]] = {}
    for skill_id, entry in registry.get("skills", {}).items():
        if not include_archived and entry.get("status") == "archived":
            continue
        entries[skill_id] = entry
    return entries


def read_skill(skill_id: str) -> Dict[str, Any]:
    registry = _load_registry()
    if skill_id in registry.get("drafts", {}):
        entry = registry["drafts"][skill_id]
        path = Path(entry["path"]) / "SKILL.md"
    else:
        normalized = skill_id if skill_id.startswith("user:") else f"user:{skill_id}"
        entry = registry.get("skills", {}).get(normalized)
        if not entry:
            try:
                from app.skills import SkillManager

                managed = SkillManager.read_skill_record(skill_id)
            except Exception:
                managed = None
            if managed:
                return managed
            raise SkillAuthoringError(f"Skill not found: {skill_id}")
        path = Path(entry["path"]) / "SKILL.md"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillAuthoringError(f"Could not read skill: {exc}") from exc
    return {**entry, "content": content}


def _reload_skill_manager() -> None:
    try:
        from app.skills import SkillManager

        SkillManager.reload_skills()
    except Exception:
        pass
