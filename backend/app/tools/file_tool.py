import difflib
import os
import aiofiles
from pathlib import Path
from typing import Any, Dict, Optional
from app.tools.base import BaseTool, ToolResult
from app.project_manager import ProjectManager
from app.security import resolve_under_base

# File operations are sandboxed under the project root or current project directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DIFF_TEXT_LIMIT = 1_000_000


def _line_stats(unified_diff: str) -> Dict[str, int]:
    added = 0
    removed = 0
    for line in unified_diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"added": added, "removed": removed}


def build_file_edit_metadata(path: Path, old_content: str, new_content: str, existed: bool) -> Dict[str, Any]:
    """Build compact, UI-friendly metadata for a text file write."""
    operation = "modify" if existed else "create"
    old_size = len(old_content.encode("utf-8", errors="ignore"))
    new_size = len(new_content.encode("utf-8", errors="ignore"))
    truncated = old_size + new_size > DIFF_TEXT_LIMIT

    if truncated:
        old_lines = old_content.count("\n") + (1 if old_content else 0)
        new_lines = new_content.count("\n") + (1 if new_content else 0)
        unified = (
            f"[Diff omitted: file content is too large for inline display. "
            f"old={old_size} bytes, new={new_size} bytes]"
        )
        stats = {
            "added": max(0, new_lines - old_lines),
            "removed": max(0, old_lines - new_lines),
        }
        return {
            "path": str(path),
            "operation": operation,
            "unified_diff": unified,
            "stats": stats,
            "truncated": True,
        }

    unified = "".join(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path.name}",
        tofile=f"b/{path.name}",
        lineterm="\n",
    ))
    stats = _line_stats(unified)
    return {
        "path": str(path),
        "operation": operation,
        "old_text": old_content,
        "new_text": new_content,
        "unified_diff": unified,
        "stats": stats,
        "truncated": False,
    }


def _get_base_path(project_relative: bool = False) -> tuple[Path, Optional[str]]:
    """Return (base_path, error_message). When error_message is set, base_path is the fallback."""
    if project_relative:
        project = ProjectManager.get_current()
        if project:
            return Path(project["path"]).resolve(), None
        return _PROJECT_ROOT, "No project is currently open. Use project_relative=false or open a project first via the sidebar."
    return _PROJECT_ROOT, None


def _validate_path(path: str, project_relative: bool = False) -> tuple[Path, Optional[str]]:
    """Validate that a path is within the sandbox. Returns (resolved_path, error_message)."""
    from app.config import load_config
    if load_config().settings.sandbox_mode == "unrestricted":
        try:
            return Path(path).resolve(), None
        except (OSError, ValueError) as e:
            return Path(path), f"Invalid path: {path} ({e})"
    base, base_err = _get_base_path(project_relative)
    if base_err:
        return base, base_err
    p, err = resolve_under_base(path, base, allow_relative=project_relative)
    if err:
        scope = "current project" if project_relative else "project root"
        return p, f"Path out of bounds: {err}. Only {scope} files under {base} are allowed."
    return p, None


class FileReadTool(BaseTool):
    name = "file_read"
    description = "Read file contents. Supports text files, auto-truncates large files. When project_relative=true, path is resolved relative to the currently opened project directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Absolute path or relative to project (when project_relative=true)"},
            "offset": {"type": "integer", "description": "Starting line number (0-indexed)", "default": 0},
            "limit": {"type": "integer", "description": "Maximum lines to read", "default": 200},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to current project directory", "default": False}
        },
        "required": ["path"]
    }

    async def execute(self, path: str, offset: int = 0, limit: int = 200, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if not p.exists():
                return ToolResult(error=f"File not found: {path}")
            if not p.is_file():
                return ToolResult(error=f"Path is not a file: {path}")

            # Safety: refuse to read overly large files
            size = p.stat().st_size
            if size > 10 * 1024 * 1024:  # 10MB
                return ToolResult(error=f"File too large ({size} bytes), refusing to read")

            async with aiofiles.open(p, "r", encoding="utf-8", errors="ignore") as f:
                lines = await f.readlines()

            selected = lines[offset:offset+limit]
            content = "".join(selected)
            info = f"\n\n[File: {p}, {len(lines)} lines, showing {offset}-{offset+len(selected)}]"
            return ToolResult(output=content + info)
        except OSError as e:
            return ToolResult(error=f"File operation error: {e}")


class FileWriteTool(BaseTool):
    name = "file_write"
    description = "Write or overwrite file contents. Creates parent directories automatically. When project_relative=true, path is resolved relative to the currently opened project directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Absolute or relative to project (when project_relative=true)"},
            "content": {"type": "string", "description": "Content to write"},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to current project directory", "default": False}
        },
        "required": ["path", "content"]
    }

    async def execute(
        self,
        path: str,
        content: str,
        project_relative: bool = False,
        run_id: str = "",
        tool_call_id: str = "",
        worker_id: str = "",
        parent_tool_call_id: str = "",
    ) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            existed = p.exists()
            old_content = ""
            if existed and p.is_file():
                try:
                    old_content = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    old_content = ""
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "w", encoding="utf-8") as f:
                await f.write(content)
            file_edit = build_file_edit_metadata(p, old_content, content, existed)
            if run_id:
                file_edit["run_id"] = run_id
            if tool_call_id:
                file_edit["tool_call_id"] = tool_call_id
            if worker_id:
                file_edit["worker_id"] = worker_id
            if parent_tool_call_id:
                file_edit["parent_tool_call_id"] = parent_tool_call_id
            return ToolResult(output=f"File written: {p}", metadata={"file_edit": file_edit})
        except OSError as e:
            return ToolResult(error=f"File operation error: {e}")


class FileListTool(BaseTool):
    name = "file_list"
    description = "List files and directories under a given path. When project_relative=true, path is resolved relative to the currently opened project directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path. Absolute or relative to project (when project_relative=true)"},
            "recursive": {"type": "boolean", "description": "List recursively", "default": False},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to current project directory", "default": False}
        },
        "required": ["path"]
    }

    async def execute(self, path: str, recursive: bool = False, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if not p.exists():
                return ToolResult(error=f"Directory not found: {path}")

            lines = []
            max_lines = 500
            if recursive:
                for item in p.rglob("*"):
                    if len(lines) >= max_lines:
                        lines.append("... (too many results, truncated)")
                        break
                    rel = item.relative_to(p)
                    marker = "[DIR]" if item.is_dir() else "[FILE]"
                    lines.append(f"{marker} {rel}")
            else:
                for item in p.iterdir():
                    if len(lines) >= max_lines:
                        lines.append("... (too many results, truncated)")
                        break
                    marker = "[DIR]" if item.is_dir() else "[FILE]"
                    lines.append(f"{marker} {item.name}")

            return ToolResult(output="\n".join(lines) if lines else "(empty directory)")
        except OSError as e:
            return ToolResult(error=f"File operation error: {e}")


class FileSearchTool(BaseTool):
    name = "file_search"
    description = "Search for files whose names contain a keyword under a given directory. When project_relative=true, path is resolved relative to the currently opened project directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Search root directory. Absolute or relative to project (when project_relative=true)"},
            "keyword": {"type": "string", "description": "Filename keyword to search for"},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to current project directory", "default": False}
        },
        "required": ["path", "keyword"]
    }

    async def execute(self, path: str, keyword: str, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            matches = []
            max_lines = 500
            for item in p.rglob(f"*{keyword}*"):
                if len(matches) >= max_lines:
                    matches.append("... (too many results, truncated)")
                    break
                matches.append(str(item.relative_to(p)))
            return ToolResult(output="\n".join(matches) if matches else "No matching files found")
        except OSError as e:
            return ToolResult(error=f"File operation error: {e}")


class FileDeleteTool(BaseTool):
    name = "file_delete"
    description = "Delete a specified file. When project_relative=true, path is resolved relative to the currently opened project directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to delete. Absolute or relative to project (when project_relative=true)"},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to current project directory", "default": False}
        },
        "required": ["path"]
    }

    async def execute(self, path: str, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if p.is_file():
                p.unlink()
                return ToolResult(output=f"Deleted: {p}")
            else:
                return ToolResult(error=f"Not a file or does not exist: {path}")
        except OSError as e:
            return ToolResult(error=f"File operation error: {e}")
