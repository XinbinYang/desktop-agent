"""文件读写工具 — 限定在工作目录内的安全文件操作"""

from __future__ import annotations

import os
from pathlib import Path

from open_agent.core.tools import ToolRegistry

_registry: ToolRegistry | None = None


def register(registry: ToolRegistry, project_dir: str) -> None:
    """将所有工具注册到给定的 registry，project_dir 用于路径限定"""
    global _registry
    _registry = registry
    _project_dir = os.path.realpath(project_dir)

    def _safe_path(path_str: str) -> Path:
        """解析路径并检查是否在工作目录内，防止目录穿越攻击"""
        p = Path(path_str)
        if not p.is_absolute():
            p = Path(_project_dir, path_str)
        resolved = os.path.realpath(str(p))
        if not resolved.startswith(_project_dir + os.sep) and resolved != _project_dir:
            raise ValueError(f"Path {path_str!r} escapes working directory")
        return Path(resolved)

    # ---- file_read ----
    def file_read(path: str, offset: int = 0, limit: int = 200) -> str:
        """Read file contents with optional offset and line limit"""
        try:
            safe = _safe_path(path)
        except ValueError as e:
            return f"Error: {e}"
        try:
            text = safe.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        lines = text.splitlines()
        if offset < 0:
            offset = max(0, len(lines) + offset)
        if offset >= len(lines):
            return ""
        end = offset + limit
        return "\n".join(lines[offset:end])

    registry.register_from_func(file_read, module="file")

    # ---- file_write ----
    def file_write(path: str, content: str) -> str:
        """Write content to a file, creating parent directories as needed"""
        try:
            safe = _safe_path(path)
        except ValueError as e:
            return f"Error: {e}"
        try:
            safe.parent.mkdir(parents=True, exist_ok=True)
            safe.write_text(content, encoding="utf-8")
        except PermissionError:
            return f"Error: permission denied: {path}"
        return f"Written {len(content)} bytes to {path}"

    registry.register_from_func(file_write, module="file")

    # ---- file_patch ----
    def file_patch(path: str, old_text: str, new_text: str) -> str:
        """Replace an exact text block in a file; fails if not unique or not found"""
        try:
            safe = _safe_path(path)
        except ValueError as e:
            return f"Error: {e}"
        try:
            original = safe.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        count = original.count(old_text)
        if count == 0:
            return f"Error: old_text not found in {path}"
        if count > 1:
            return f"Error: old_text appears {count} times in {path}; must be unique"
        updated = original.replace(old_text, new_text, 1)
        try:
            safe.write_text(updated, encoding="utf-8")
        except PermissionError:
            return f"Error: permission denied: {path}"
        return f"Patched {path} successfully"

    registry.register_from_func(file_patch, module="file")

    # ---- file_list ----
    def file_list(path: str = ".", recursive: bool = False) -> str:
        """List directory contents in a formatted tree"""
        try:
            safe = _safe_path(path)
        except ValueError as e:
            return f"Error: {e}"
        if not safe.exists():
            return f"Error: path not found: {path}"
        if not safe.is_dir():
            return f"Error: not a directory: {path}"
        entries = sorted(safe.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        lines = []
        for entry in entries:
            prefix = "📁" if entry.is_dir() else "📄"
            name = entry.name
            if recursive and entry.is_dir():
                lines.append(f"{prefix} {name}/")
                for sub in sorted(entry.rglob("*"), key=lambda p: (not p.is_dir(), str(p).lower())):
                    indent = "  " * (len(sub.relative_to(safe).parts) - 1)
                    sp = "📁" if sub.is_dir() else "📄"
                    lines.append(f"  {indent}{sp} {sub.relative_to(safe)}")
            else:
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix} {name}{suffix}")
        return "\n".join(lines)

    registry.register_from_func(file_list, module="file")
