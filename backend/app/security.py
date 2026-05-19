import json
import os
import re
import secrets
from pathlib import Path
from typing import Optional, Tuple


AUTH_TOKEN_ENV = "DESKTOP_AGENT_AUTH_TOKEN"
AUTH_HEADER = "X-Desktop-Agent-Token"
SENSITIVE_KEYS = ("token", "password", "secret", "api_key", "authorization")
AUTH_FILE_NAME = "local-auth.json"
_MIN_TOKEN_LEN = 32


def is_relative_to(path: Path, base: Path) -> bool:
    """Return true when path is inside base using pathlib semantics."""
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def resolve_under_base(path: str, base: Path, *, allow_relative: bool = True) -> Tuple[Path, Optional[str]]:
    """Resolve a user supplied path and ensure it stays under base.

    Relative paths are always anchored to ``base``, never to the process
    current working directory. (The backend process runs with cwd=backend/,
    so cwd-relative resolution silently wrote agent files to backend/AGENTS/.)
    ``allow_relative`` is retained for signature stability only.
    """
    resolved_base = base.resolve()
    try:
        raw_path = Path(path)
        resolved = raw_path.resolve() if raw_path.is_absolute() else (resolved_base / raw_path).resolve()
    except (OSError, ValueError) as e:
        return Path(path), f"Invalid path: {path} ({e})"

    if not is_relative_to(resolved, resolved_base):
        return resolved, f"Path escapes allowed directory: {path}"
    return resolved, None


def resolve_current_project_file(path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a file path against the currently opened project."""
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return None, "No project is currently open"

    resolved, err = resolve_under_base(path, Path(project["path"]), allow_relative=True)
    if err:
        return None, err
    return resolved, None


def _read_auth_token_file() -> str:
    """Read the token Electron persisted to userData/local-auth.json.

    Lets the backend honor the same token in dev mode where Electron starts
    the user-data dir but does not pass an env var to a separately-launched
    backend process (e.g. start-all.ps1 workflow).
    """
    from app.runtime_paths import user_data_dir

    base = user_data_dir()
    auth_file = base / AUTH_FILE_NAME
    if not auth_file.exists():
        return ""
    try:
        data = json.loads(auth_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    token = data.get("token", "") if isinstance(data, dict) else ""
    if isinstance(token, str) and len(token) >= _MIN_TOKEN_LEN:
        return token
    return ""


def get_auth_token() -> str:
    env_token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if env_token:
        return env_token
    return _read_auth_token_file()


def is_auth_enabled() -> bool:
    return bool(get_auth_token())


def is_valid_auth_token(token: Optional[str]) -> bool:
    expected = get_auth_token()
    if not expected:
        return False
    if not token:
        return False
    return secrets.compare_digest(token, expected)


_REDACT_PATTERNS = [
    # HTTP auth headers — capture the prefix so we keep "Authorization: Basic " readable.
    (re.compile(r"(Authorization:\s*Basic\s+)[A-Za-z0-9+/=]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(Authorization:\s*Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(x-api-key:\s*)[A-Za-z0-9._\-]+", re.IGNORECASE), r"\1[REDACTED]"),
    # GitHub PATs (ghp_/ghs_/gho_/ghu_/ghr_) and OAuth client tokens.
    (re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{12,}\b"), "[REDACTED]"),
    # GitLab personal / project / deploy / runner / oauth tokens.
    (re.compile(r"(?i)\bglpat-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\bglptt-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED]"),
    (re.compile(r"(?i)\bgldt-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED]"),
    # OpenAI / Anthropic / generic sk- prefixed keys.
    (re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{12,}\b"), "[REDACTED]"),
    # Slack tokens.
    (re.compile(r"\bxox[pbaroe]-[A-Za-z0-9\-]{10,}\b"), "[REDACTED]"),
    # AWS access keys.
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED]"),
]


def redact_sensitive_text(text: str) -> str:
    """Best-effort redaction for logs and tool outputs.

    Covers the secret formats most likely to leak from `git` and HTTP error
    output: HTTP auth headers, GitHub/GitLab PATs, OpenAI/Anthropic keys,
    Slack tokens, and AWS access keys. Designed to be fast (single pass per
    pattern, all pre-compiled) so it can wrap every git stdout line.
    """
    redacted = text
    for pattern, repl in _REDACT_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def redact_mapping(data: dict) -> dict:
    """Return a shallow copy with sensitive values replaced."""
    result = {}
    for key, value in data.items():
        if any(marker in key.lower() for marker in SENSITIVE_KEYS):
            result[key] = "[REDACTED]" if value else value
        else:
            result[key] = value
    return result
