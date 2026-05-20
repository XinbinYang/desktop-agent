from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.coding_runs import effective_project_path
from app.project_manager import ProjectManager


TARGET_REQUIRED_MESSAGE = (
    "Coding Agent needs a target project path for this task. Provide project_path "
    "or mention an absolute local project directory in the request."
)

_CONTEXT_PATH_KEYS = (
    "project_path",
    "target_path",
    "target_project_path",
    "repo_path",
    "workspace_path",
    "cwd",
)
_WRAPPED_PATH_RE = re.compile(r"[`\"']([^`\"']+)[`\"']")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:[\\/][^\r\n`\"'<>|]+")
_POSIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s`\"'<>|]+/?)+")
_TRAILING_CHARS = " \t\r\n.,;:)]}" + "\uFF0C\u3002\uFF1B\uFF1A\u3001\uFF09\u3011"


@dataclass(frozen=True)
class CollaborationTarget:
    project_path: str = ""
    source: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.project_path) and not self.error


def _clean_candidate(value: str) -> str:
    return str(value or "").strip().strip("`\"'").rstrip(_TRAILING_CHARS)


def _normalize_existing_project_path(value: Any) -> str:
    raw = _clean_candidate(str(value or ""))
    if not raw:
        return ""
    try:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            return ""
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        return ""
    if not resolved.exists() or not resolved.is_dir():
        return ""
    canonical = ProjectManager.canonical_project_path(resolved)
    try:
        canonical_path = Path(canonical).resolve() if canonical else resolved
    except (OSError, RuntimeError, ValueError):
        canonical_path = resolved
    return str(canonical_path) if canonical_path.exists() and canonical_path.is_dir() else ""


def _invalid_explicit_error(source: str, value: Any) -> str:
    return f"Coding Agent target path from {source} is not an existing absolute directory: {value}"


def _context_path_values(context: dict[str, Any] | None) -> Iterable[tuple[str, Any]]:
    if not isinstance(context, dict):
        return []
    values: list[tuple[str, Any]] = []
    for key in _CONTEXT_PATH_KEYS:
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            values.append((f"context.{key}", value))
    target = context.get("target")
    if isinstance(target, dict):
        for key in _CONTEXT_PATH_KEYS:
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                values.append((f"context.target.{key}", value))
    return values


def _existing_absolute_prefix(raw_value: str) -> str:
    raw = _clean_candidate(raw_value)
    if not raw:
        return ""
    direct = _normalize_existing_project_path(raw)
    if direct:
        return direct
    for end in range(len(raw) - 1, 2, -1):
        prefix = raw[:end].rstrip(_TRAILING_CHARS)
        if not prefix:
            continue
        path = _normalize_existing_project_path(prefix)
        if path:
            return path
    return ""


def _mentioned_path_values(text: str) -> Iterable[str]:
    if not text:
        return []
    values: list[str] = []
    values.extend(match.group(1) for match in _WRAPPED_PATH_RE.finditer(text))
    values.extend(match.group(0) for match in _WINDOWS_PATH_RE.finditer(text))
    values.extend(match.group(0) for match in _POSIX_PATH_RE.finditer(text))
    return values


def resolve_collaboration_target(
    *,
    project_path: str | None = None,
    context: dict[str, Any] | None = None,
    user_message: str = "",
    allow_global: bool = True,
) -> CollaborationTarget:
    """Resolve the project directory for a Personal-to-Coding collaboration task.

    Priority:
      1. Explicit tool argument.
      2. Structured context path.
      3. Absolute local path mentioned in the user message.
      4. Current UI project as a legacy fallback.
    """
    if project_path and str(project_path).strip():
        resolved = _normalize_existing_project_path(project_path)
        if resolved:
            return CollaborationTarget(project_path=resolved, source="project_path")
        return CollaborationTarget(error=_invalid_explicit_error("project_path", project_path))

    for source, value in _context_path_values(context):
        resolved = _normalize_existing_project_path(value)
        if resolved:
            return CollaborationTarget(project_path=resolved, source=source)
        return CollaborationTarget(error=_invalid_explicit_error(source, value))

    mentioned_any = False
    for value in _mentioned_path_values(user_message):
        mentioned_any = True
        resolved = _existing_absolute_prefix(value)
        if resolved:
            return CollaborationTarget(project_path=resolved, source="message")
    if mentioned_any:
        return CollaborationTarget(
            error="Coding Agent target path mentioned in the request was not an existing absolute directory."
        )

    if allow_global:
        fallback = effective_project_path(allow_global=True)
        resolved = _normalize_existing_project_path(fallback)
        if resolved:
            return CollaborationTarget(project_path=resolved, source="current_project")

    return CollaborationTarget(error=TARGET_REQUIRED_MESSAGE)
