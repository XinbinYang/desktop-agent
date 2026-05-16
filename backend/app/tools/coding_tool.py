"""Coding-agent helper tools: search, outline, patch, verify, review, worktree status."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.coding_context import build_repo_map, current_project_path, format_repo_map_summary, outline_file, run_code_search
from app.coding_runs import get_run_context, record_event, worktree_status
from app.tools.base import BaseTool, ToolResult
from app.tools.file_tool import DIFF_TEXT_LIMIT, _validate_path, build_file_edit_metadata


def _active_project_root() -> tuple[Optional[Path], Optional[str]]:
    ctx = get_run_context()
    if ctx and ctx.active_path:
        return Path(ctx.active_path).resolve(), None
    root = current_project_path()
    if root:
        return root, None
    return None, "No project is currently open"


def _resolve_active_path(path: str) -> tuple[Optional[Path], Optional[str]]:
    root, err = _active_project_root()
    if err:
        return None, err
    assert root is not None
    try:
        raw = Path(path)
        resolved = (root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    except (OSError, ValueError) as exc:
        return None, f"Invalid path: {path} ({exc})"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, f"Path escapes active project: {path}"
    return resolved, None


class RepoMapTool(BaseTool):
    name = "repo_map"
    description = "Build a concise codebase map for the current project: languages, entrypoints, commands, and key symbols."
    parameters = {
        "type": "object",
        "properties": {
            "max_files": {"type": "integer", "description": "Maximum text/code files to scan", "default": 220},
            "format": {"type": "string", "enum": ["summary", "json"], "default": "summary"},
        },
    }

    async def execute(self, max_files: int = 220, format: str = "summary") -> ToolResult:
        root, err = _active_project_root()
        if err:
            return ToolResult(error=err)
        repo_map = build_repo_map(str(root), max_files=max(20, min(max_files, 1000)))
        if format == "json":
            return ToolResult(output=json.dumps(repo_map, ensure_ascii=False, indent=2), metadata={"repo_map": repo_map})
        return ToolResult(output=format_repo_map_summary(repo_map), metadata={"repo_map": repo_map})


class CodeSearchTool(BaseTool):
    name = "code_search"
    description = "Search code contents with rg-style output. Prefer this over shell grep/findstr for repository search."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search string or regex"},
            "path": {"type": "string", "description": "Optional project-relative search path", "default": ""},
            "file_glob": {"type": "string", "description": "Optional glob such as *.py or frontend/src/**/*.tsx", "default": ""},
            "context_lines": {"type": "integer", "description": "Context lines around matches", "default": 2},
            "max_results": {"type": "integer", "description": "Maximum match groups", "default": 80},
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        path: str = "",
        file_glob: str = "",
        context_lines: int = 2,
        max_results: int = 80,
    ) -> ToolResult:
        root, err = _active_project_root()
        if err:
            return ToolResult(error=err)
        assert root is not None
        output = run_code_search(
            query=query,
            root=root,
            path=path,
            file_glob=file_glob,
            context_lines=max(0, min(context_lines, 5)),
            max_results=max(1, min(max_results, 500)),
        )
        return ToolResult(output=output)


class FileOutlineTool(BaseTool):
    name = "file_outline"
    description = "Return a compact structural outline of a source file: imports, classes, functions, and React-style components."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Project-relative file path"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str) -> ToolResult:
        p, err = _resolve_active_path(path)
        if err:
            return ToolResult(error=err)
        assert p is not None
        if not p.exists() or not p.is_file():
            return ToolResult(error=f"File not found: {path}")
        if p.stat().st_size > 2 * 1024 * 1024:
            return ToolResult(error=f"File too large for outline: {p.stat().st_size} bytes")
        data = outline_file(p)
        return ToolResult(output=json.dumps(data, ensure_ascii=False, indent=2), metadata={"file_outline": data})


class FilePatchTool(BaseTool):
    name = "file_patch"
    description = "Patch an existing text file by replacing an exact old_text block with new_text. Prefer this over file_write for modifying code."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path. Absolute or relative to project when project_relative=true"},
            "old_text": {"type": "string", "description": "Exact text to replace"},
            "new_text": {"type": "string", "description": "Replacement text"},
            "occurrence": {"type": "integer", "description": "1-based occurrence to replace when old_text appears multiple times"},
            "project_relative": {"type": "boolean", "description": "Resolve path relative to active/current project", "default": True},
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def execute(
        self,
        path: str,
        old_text: str,
        new_text: str,
        occurrence: Optional[int] = None,
        project_relative: bool = True,
    ) -> ToolResult:
        p, err = _validate_path(path, project_relative=project_relative)
        if err:
            return ToolResult(error=err)
        if not old_text:
            return ToolResult(error="old_text must not be empty")
        try:
            if not p.exists() or not p.is_file():
                return ToolResult(error=f"File not found: {path}")
            if p.stat().st_size > DIFF_TEXT_LIMIT:
                return ToolResult(error=f"File too large for exact patch: {p.stat().st_size} bytes")
            original = p.read_text(encoding="utf-8", errors="ignore")
            count = original.count(old_text)
            if count == 0:
                needle = old_text.strip().splitlines()[0][:80] if old_text.strip() else ""
                candidates = []
                if needle:
                    for idx, line in enumerate(original.splitlines(), start=1):
                        if needle[:30] and needle[:30] in line:
                            candidates.append(f"{idx}: {line[:180]}")
                            if len(candidates) >= 5:
                                break
                hint = "\nNearby candidates:\n" + "\n".join(candidates) if candidates else ""
                return ToolResult(error=f"old_text not found in {p}.{hint}")
            if count > 1 and occurrence is None:
                return ToolResult(error=f"old_text appears {count} times in {p}; provide occurrence (1-based)")
            target = occurrence or 1
            if target < 1 or target > count:
                return ToolResult(error=f"occurrence must be between 1 and {count}")
            start = -1
            pos = 0
            for _ in range(target):
                start = original.find(old_text, pos)
                pos = start + len(old_text)
            updated = original[:start] + new_text + original[start + len(old_text):]
            p.write_text(updated, encoding="utf-8")
            edit = build_file_edit_metadata(p, original, updated, True)
            return ToolResult(output=f"Patched: {p}", metadata={"file_edit": edit})
        except OSError as exc:
            return ToolResult(error=f"File patch error: {exc}")


class VerifyProjectTool(BaseTool):
    name = "verify_project"
    description = "Run the smallest detected verification command for the active project and return structured pass/fail output."
    parameters = {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "enum": ["auto", "test", "lint", "typecheck", "build"], "default": "auto"},
            "changed_files": {"type": "array", "items": {"type": "string"}, "description": "Optional changed files for context"},
            "command_override": {"type": "string", "description": "Explicit command to run instead of auto detection"},
        },
    }

    async def execute(
        self,
        scope: str = "auto",
        changed_files: Optional[List[str]] = None,
        command_override: str = "",
    ) -> ToolResult:
        from app.coding_context import detect_commands

        root, err = _active_project_root()
        if err:
            return ToolResult(error=err)
        assert root is not None
        commands = detect_commands(root)
        command = command_override.strip()
        if not command:
            if scope != "auto" and scope in commands:
                command = commands[scope]
            else:
                for key in ("test", "typecheck", "lint", "build"):
                    if key in commands:
                        command = commands[key]
                        break
        if not command:
            return ToolResult(error="No verification command detected; pass command_override")

        started = time.time()
        try:
            proc = subprocess.run(command, cwd=str(root), shell=True, capture_output=True, text=True, timeout=120)
            duration_ms = round((time.time() - started) * 1000)
        except subprocess.TimeoutExpired:
            duration_ms = round((time.time() - started) * 1000)
            data = {
                "command": command,
                "cwd": str(root),
                "exit_code": 124,
                "duration_ms": duration_ms,
                "passed": False,
                "summary": "Verification timed out after 120s",
                "changed_files": changed_files or [],
            }
            return ToolResult(error=data["summary"], metadata={"verification": data})

        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        summary = output[-8000:] if output else "(no output)"
        data = {
            "command": command,
            "cwd": str(root),
            "exit_code": proc.returncode,
            "duration_ms": duration_ms,
            "passed": proc.returncode == 0,
            "summary": summary,
            "changed_files": changed_files or [],
        }
        text = f"{'PASSED' if data['passed'] else 'FAILED'}: {command}\n{summary}"
        return ToolResult(output=text, metadata={"verification": data})


class RunReviewTool(BaseTool):
    name = "run_review"
    description = "Review the current run diff for obvious blocking risks and return structured findings."
    parameters = {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "Optional run id; defaults to active run"},
        },
    }

    async def execute(self, run_id: str = "") -> ToolResult:
        ctx = get_run_context()
        rid = run_id or (ctx.run_id if ctx else "")
        root, err = _active_project_root()
        if err:
            return ToolResult(error=err)
        assert root is not None
        proc = subprocess.run(["git", "diff", "--stat"], cwd=str(root), capture_output=True, text=True, timeout=30)
        stat = proc.stdout.strip()
        proc2 = subprocess.run(["git", "diff", "--", "."], cwd=str(root), capture_output=True, text=True, timeout=30)
        diff = proc2.stdout
        findings = []
        if len(diff) > 200_000:
            findings.append({"severity": "important", "message": "Diff is very large; manual review recommended"})
        for token in ("TODO", "FIXME", "console.log(", "debugger;"):
            if token in diff:
                findings.append({"severity": "minor", "message": f"Diff contains {token}"})
        data = {"run_id": rid, "findings": findings, "diff_stat": stat}
        if rid:
            for finding in findings:
                record_event(rid, "review_finding", {"run_id": rid, **finding})
        output = "No blocking findings" if not findings else json.dumps(findings, ensure_ascii=False, indent=2)
        if stat:
            output += f"\n\nDiff stat:\n{stat}"
        return ToolResult(output=output, metadata={"review": data})


class WorktreeStatusTool(BaseTool):
    name = "worktree_status"
    description = "Show status and diff stat for a coding run worktree."
    parameters = {
        "type": "object",
        "properties": {
            "run_id": {"type": "string", "description": "Optional run id; defaults to active run"},
        },
    }

    async def execute(self, run_id: str = "") -> ToolResult:
        ctx = get_run_context()
        rid = run_id or (ctx.run_id if ctx else "")
        if not rid:
            return ToolResult(error="No run_id provided and no active coding run")
        data = worktree_status(rid)
        if data.get("error"):
            return ToolResult(error=data["error"])
        return ToolResult(output=json.dumps(data, ensure_ascii=False, indent=2), metadata={"worktree_status": data})
