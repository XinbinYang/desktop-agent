"""
DEPRECATED — Use app.agents.manager.AgentManager instead.

This module is kept for backward compatibility. All public APIs forward to AgentManager.
"""

import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Role:
    id: str
    name: str
    description: str
    prompt_template: str
    is_builtin: bool = True


class RoleManager:
    BUILTIN_DIR = Path(__file__).parent.parent / "prompts" / "roles"
    _roles: Optional[List[Role]] = None

    @classmethod
    def _parse_md(cls, path: Path) -> Role:
        """解析带 YAML frontmatter 的 markdown 角色文件。"""
        content = path.read_text(encoding="utf-8")
        role_id = path.stem

        # 解析 YAML frontmatter: ---\n...\n---
        frontmatter = {}
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                fm_text = content[3:end].strip()
                content = content[end + 3:].strip()
                for line in fm_text.split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        frontmatter[key.strip()] = val.strip()

        return Role(
            id=role_id,
            name=frontmatter.get("name", role_id),
            description=frontmatter.get("description", ""),
            prompt_template=content,
            is_builtin=True,
        )

    @classmethod
    def load_builtin_roles(cls) -> List[Role]:
        if cls._roles is not None:
            return cls._roles

        roles = []
        if cls.BUILTIN_DIR.exists():
            for path in sorted(cls.BUILTIN_DIR.glob("*.md")):
                if path.stem.startswith("_"):
                    continue  # skip internal/shared templates
                try:
                    roles.append(cls._parse_md(path))
                except Exception as e:
                    print(f"[RoleManager] Failed to load {path}: {e}")
        cls._roles = roles
        return roles

    @classmethod
    def get_role(cls, role_id: str) -> Optional[Role]:
        for r in cls.load_builtin_roles():
            if r.id == role_id:
                return r
        return None

    @classmethod
    def render_prompt(cls, role_id: str, tools_desc: str) -> str:
        role = cls.get_role(role_id)
        if role is None:
            # fallback to desktop-agent
            role = cls.get_role("desktop-agent")
        if role is None:
            return f"你是一个桌面个人 Agent。\n\n当前可用工具:\n{tools_desc}"

        template = role.prompt_template

        # Inject shared base template
        base_path = cls.BUILTIN_DIR / "_base.md"
        if base_path.exists():
            base_role = cls._parse_md(base_path)
            template = template.replace("{{base}}", base_role.prompt_template)

        return template.replace("{{tools_desc}}", tools_desc)

    @classmethod
    def list_roles(cls) -> List[dict]:
        return [
            {"id": r.id, "name": r.name, "description": r.description, "is_builtin": r.is_builtin}
            for r in cls.load_builtin_roles()
        ]

    @classmethod
    def reload(cls):
        cls._roles = None
