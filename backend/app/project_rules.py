"""Project-level agent rules — the .desktop-agent.md equivalent of CLAUDE.md."""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Optional


PROJECT_RULES_FILE = ".desktop-agent.md"
USER_RULES_FILE = "AGENTS.md"
USER_RULES_DIR = ".desktop-agent"


def _resolve_template(value: str, project_path: str = "", branch: str = "") -> str:
    """Replace template variables in rules content."""
    return (
        value
        .replace("{{project_path}}", project_path)
        .replace("{{project_name}}", Path(project_path).name if project_path else "")
        .replace("{{branch}}", branch)
        .replace("{{os}}", platform.system())
        .replace("{{platform}}", platform.platform())
        .replace("{{user}}", os.environ.get("USER", os.environ.get("USERNAME", "")))
        .replace("{{home}}", str(Path.home()))
    )


def _read_rules_file(path: Path, max_size: int = 64 * 1024) -> Optional[str]:
    """Read a rules file, skipping binary or oversize files."""
    try:
        if not path.exists() or not path.is_file():
            return None
        if path.stat().st_size > max_size:
            return None
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def get_project_rules(project_path: str, branch: str = "") -> Optional[str]:
    """Return the content of <project_root>/.desktop-agent.md if it exists."""
    if not project_path:
        return None
    rules_path = Path(project_path) / PROJECT_RULES_FILE
    content = _read_rules_file(rules_path)
    if content:
        content = _resolve_template(content, project_path, branch)
    return content


def get_user_rules() -> Optional[str]:
    """Return the content of ~/.desktop-agent/AGENTS.md if it exists."""
    rules_path = Path.home() / USER_RULES_DIR / USER_RULES_FILE
    content = _read_rules_file(rules_path)
    if content:
        content = _resolve_template(content)
    return content


def build_rules_prompt(project_path: str = "", branch: str = "") -> str:
    """Build the combined rules section for injection into the system prompt."""
    parts: list[str] = []

    user_rules = get_user_rules()
    if user_rules:
        parts.append(f"## User Rules (~/.desktop-agent/AGENTS.md)\n{user_rules}")

    project_rules = get_project_rules(project_path, branch)
    if project_rules:
        parts.append(f"## Project Rules (.desktop-agent.md)\n{project_rules}")

    if parts:
        # User rules first, project rules override (user intent takes precedence)
        return "\n\n" + "\n\n".join(parts)

    return ""
