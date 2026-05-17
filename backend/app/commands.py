"""Slash command registry — built-in commands available in the chat input."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class CommandInfo:
    name: str
    description: str
    args: str = ""           # e.g. "<model_id>" or "[option]"
    category: str = "general"
    handler: Optional[str] = None  # frontend action name, or None for agent-forwarded


# ── built-in commands ───────────────────────────────────────────────────────

BUILTIN_COMMANDS: List[CommandInfo] = [
    CommandInfo(
        name="help",
        description="显示帮助信息和可用命令列表",
        category="general",
    ),
    CommandInfo(
        name="clear",
        description="清除当前会话的所有消息",
        category="session",
    ),
    CommandInfo(
        name="new",
        description="Start a fresh session; Coding creates a new session, Personal clears the current one.",
        category="session",
    ),
    CommandInfo(
        name="compact",
        description="压缩对话上下文，生成摘要并释放 token",
        category="session",
    ),
    CommandInfo(
        name="rewind",
        description="Rewind to a previous user-message checkpoint and retry from there.",
        category="session",
    ),
    CommandInfo(
        name="context",
        description="Show current context usage and source breakdown.",
        category="session",
    ),
    CommandInfo(
        name="model",
        description="切换模型",
        args="<model_id>",
        category="session",
    ),
    CommandInfo(
        name="role",
        description="切换角色",
        args="<role_id>",
        category="session",
    ),
    CommandInfo(
        name="project",
        description="打开项目",
        args="<path>",
        category="project",
    ),
    CommandInfo(
        name="config",
        description="打开设置面板",
        category="general",
    ),
    CommandInfo(
        name="screenshot",
        description="截取当前屏幕",
        category="tools",
    ),
    CommandInfo(
        name="skills",
        description="列出可用的技能",
        category="general",
    ),
]


def get_commands() -> List[Dict[str, Any]]:
    """Return all registered commands as JSON-serializable dicts."""
    result = []
    for cmd in BUILTIN_COMMANDS:
        result.append({
            "name": cmd.name,
            "description": cmd.description,
            "args": cmd.args,
            "category": cmd.category,
        })
    # Also register skills as commands
    try:
        from app.skills import SkillManager
        skills = SkillManager.list_skills()
        for skill in skills:
            result.append({
                "name": skill["id"] if isinstance(skill, dict) else skill.name,
                "description": skill.get("description", "") if isinstance(skill, dict) else skill.description,
                "args": "",
                "category": "skills",
            })
    except Exception:
        pass
    return result
