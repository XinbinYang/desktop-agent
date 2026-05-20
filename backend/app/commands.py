"""Slash command registry: built-in commands available in the chat input."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CommandInfo:
    name: str
    description: str
    args: str = ""
    category: str = "general"
    handler: Optional[str] = None


BUILTIN_COMMANDS: List[CommandInfo] = [
    CommandInfo(
        name="help",
        description="Show help and available slash commands.",
        category="general",
    ),
    CommandInfo(
        name="clear",
        description="Clear the visible chat and backend session transcript.",
        category="session",
    ),
    CommandInfo(
        name="reset",
        description="Start a fresh model context in this session while keeping visible chat history.",
        category="session",
    ),
    CommandInfo(
        name="new",
        description="Start a fresh context in this pane and let the agent greet you.",
        category="session",
    ),
    CommandInfo(
        name="compact",
        description="Compact the active context into a summary to free tokens.",
        category="session",
    ),
    CommandInfo(
        name="rewind",
        description="Rewind to a previous user-message checkpoint and retry from there.",
        category="session",
    ),
    CommandInfo(
        name="context",
        description="Show active context usage and source breakdown.",
        category="session",
    ),
    CommandInfo(
        name="model",
        description="Switch the focused session model.",
        args="<model_id>",
        category="session",
    ),
    CommandInfo(
        name="role",
        description="Switch the focused session role.",
        args="<role_id>",
        category="session",
    ),
    CommandInfo(
        name="project",
        description="Open a project folder.",
        args="<path>",
        category="project",
    ),
    CommandInfo(
        name="config",
        description="Open settings.",
        category="general",
    ),
    CommandInfo(
        name="screenshot",
        description="Capture the current screen.",
        category="tools",
    ),
    CommandInfo(
        name="skills",
        description="Open available skills.",
        category="general",
    ),
]


def get_commands() -> List[Dict[str, Any]]:
    """Return all registered commands as JSON-serializable dicts."""
    return [
        {
            "name": cmd.name,
            "description": cmd.description,
            "args": cmd.args,
            "category": cmd.category,
        }
        for cmd in BUILTIN_COMMANDS
    ]
