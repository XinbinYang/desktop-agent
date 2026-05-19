"""
Team shared context — a Markdown file per team stored under the runtime directory.

Path: ``{runtime_root}/teams/{team_id}.md``
"""

from pathlib import Path
from .runtime_paths import runtime_dir

TEAMS_DIR = runtime_dir("teams")


def _team_file(team_id: str) -> Path:
    # Sanitize: only allow alphanumeric, dash, underscore
    safe = "".join(c for c in team_id if c.isalnum() or c in "_-")
    return TEAMS_DIR / f"{safe}.md"


def read_team_context(team_id: str) -> str:
    """Read the shared context file for a team. Returns empty string if missing."""
    path = _team_file(team_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def append_team_context(team_id: str, content: str) -> None:
    """Append a timestamped entry to the team shared context."""
    path = _team_file(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n\n## {_now_tag()}\n{content.strip()}"
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def write_team_context(team_id: str, content: str) -> None:
    """Overwrite the entire team context file."""
    path = _team_file(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip(), encoding="utf-8")


def build_team_context_prompt(team_id: str, team_name: str) -> str:
    """Build the system prompt section for a team's shared context."""
    ctx = read_team_context(team_id)
    if not ctx:
        return ""
    return (
        f"\n\n## Team Context (团队: {team_name})\n\n"
        f"你属于团队「{team_name}」。以下是团队共享上下文,所有成员可见。\n"
        f"你可以使用 `team_context` 工具读取和更新团队共享上下文。\n"
        f"其他成员的更新会在下一轮对话中自动反映。\n\n"
        f"{ctx}"
    )


def _now_tag() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
