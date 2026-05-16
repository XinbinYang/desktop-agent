"""Lightweight tool guardrails for local coding-agent runs."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.coding_runs import RunContext, get_run_context


def _match_pattern(pattern: str, value: str) -> bool:
    """Match a value against a wildcard pattern (*, ? supported)."""
    if not pattern:
        return True  # Empty pattern matches everything
    return fnmatch.fnmatch(value.lower(), pattern.lower())


def _check_auto_approve_rules(
    tool_name: str,
    tool_args: Dict[str, Any],
    risk: str,
) -> Optional[str]:
    """Check user-configured auto-approve rules. Returns 'allow', 'deny', or None."""
    from app.config import load_config

    try:
        rules: List[Any] = load_config().settings.auto_approve_rules
    except Exception:
        return None

    if not rules:
        return None

    path = str(tool_args.get("path") or tool_args.get("file_path") or "")
    for rule in rules:
        if not _match_pattern(rule.tool, tool_name):
            continue
        if not _match_pattern(rule.path, path):
            continue
        if rule.risk and rule.risk.lower() != risk.lower():
            continue
        return rule.action

    return None


def evaluate_auto_approve(tool_name: str, tool_args: Dict[str, Any]) -> bool:
    """Return True if user rules explicitly allow this tool call.

    Used by the agent loop to skip the approval prompt for matching calls.
    """
    result = _check_auto_approve_rules(tool_name, tool_args, "low")
    if result == "allow":
        return True
    if result == "deny":
        return False
    # Fall back to global auto_approve setting
    from app.config import load_config
    try:
        return load_config().settings.auto_approve
    except Exception:
        return False


DANGEROUS_COMMANDS = [
    re.compile(r"\bgit\s+reset\s+--hard\b", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-", re.IGNORECASE),
    re.compile(r"\bgit\s+checkout\s+\.", re.IGNORECASE),
    re.compile(r"\bgit\s+branch\s+-D\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b.*-Recurse\b.*-Force\b", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+[/~]?", re.IGNORECASE),
    re.compile(r"\bformat\s+[A-Za-z]:", re.IGNORECASE),
    re.compile(r"\bdel\s+/[fsq]", re.IGNORECASE),
]

SECRET_PATTERNS = [
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{12,}\b"),
    re.compile(r"(?i)\bglpat-[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[pbaroe]-[A-Za-z0-9\-]{10,}\b"),
]

TEST_PATH_PATTERN = re.compile(r"(^|[\\/])(tests?|__tests__)[\\/]|(^|[\\/])test_[^\\/]+\.py$|\.test\.[tj]sx?$|\.spec\.[tj]sx?$", re.IGNORECASE)
TEST_EDIT_INTENT_PATTERN = re.compile(
    r"(?i)(add|write|create|update|modify|refactor)\s+(a\s+)?(unit\s+|integration\s+)?tests?\b|"
    r"\btests?\s+(to cover|coverage)\b|"
    r"新增.*测试|添加.*测试|编写.*测试|修改.*测试|更新.*测试|补.*测试|测试用例"
)
NON_PORTABLE_COMMANDS = [
    re.compile(r"(^|[;&|])\s*(tail|head|grep|sed|awk)\b", re.IGNORECASE),
]


def _decision(
    tool_name: str,
    risk: str,
    decision: str,
    reason: str,
    requires_approval: bool = False,
    tool_call_id: str = "",
    run_id: str = "",
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "risk": risk,
        "decision": decision,
        "reason": reason,
        "requires_approval": requires_approval,
    }


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)


def _is_test_path(path: str) -> bool:
    return bool(TEST_PATH_PATTERN.search((path or "").replace("\\", "/")))


def _prompt_allows_test_edits(prompt: str, extra_context: str = "") -> bool:
    combined = f"{prompt or ''} {extra_context or ''}"
    return bool(TEST_EDIT_INTENT_PATTERN.search(combined))


def _path_points_to_original_project(path: str, ctx: RunContext) -> bool:
    if not path:
        return False
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return False
    project = Path(ctx.project_path).resolve()
    worktree = Path(ctx.worktree_path).resolve() if ctx.worktree_path else None
    try:
        p.relative_to(project)
        if worktree:
            try:
                p.relative_to(worktree)
                return False
            except ValueError:
                return True
    except ValueError:
        return False
    return False


def evaluate_pre_tool(
    tool_name: str,
    tool_args: Dict[str, Any],
    *,
    run_id: str = "",
    tool_call_id: str = "",
    ctx: Optional[RunContext] = None,
    conversation_context: str = "",
) -> Dict[str, Any]:
    ctx = ctx or get_run_context()

    if tool_name in {"shell_execute", "shell_start", "verify_project"}:
        command = str(tool_args.get("command") or tool_args.get("command_override") or "")
        for pattern in DANGEROUS_COMMANDS:
            if pattern.search(command):
                return _decision(
                    tool_name,
                    "high",
                    "blocked",
                    f"Blocked dangerous shell command pattern: {pattern.pattern}",
                    True,
                    tool_call_id,
                    run_id,
                )
        for pattern in NON_PORTABLE_COMMANDS:
            if pattern.search(command):
                return _decision(
                    tool_name,
                    "medium",
                    "blocked",
                    "Blocked non-portable Unix shell helper on Windows; use PowerShell cmdlets or `rg` instead",
                    False,
                    tool_call_id,
                    run_id,
                )

    if tool_name in {"file_write", "file_patch"}:
        path = str(tool_args.get("path") or "")
        if ctx and _is_test_path(path) and not _prompt_allows_test_edits(ctx.prompt, conversation_context):
            return _decision(
                tool_name,
                "high",
                "blocked",
                "Blocked test-file edit because the task did not explicitly ask to add or modify tests. Fix implementation code instead.",
                True,
                tool_call_id,
                run_id,
            )
        content = str(tool_args.get("content") or tool_args.get("new_text") or "")
        if _contains_secret(content):
            return _decision(
                tool_name,
                "high",
                "blocked",
                "Blocked likely secret in file content",
                True,
                tool_call_id,
                run_id,
            )

    if ctx and ctx.mode == "worktree" and tool_name in {"file_write", "file_patch", "file_delete"}:
        path = str(tool_args.get("path") or "")
        if _path_points_to_original_project(path, ctx):
            return _decision(
                tool_name,
                "high",
                "blocked",
                "Blocked write to original project while run is isolated in a worktree",
                True,
                tool_call_id,
                run_id,
            )

    return _decision(tool_name, "low", "allowed", "Allowed by default tool guardrails", False, tool_call_id, run_id)


def evaluate_post_tool(
    tool_name: str,
    result_text: str,
    metadata: Dict[str, Any],
    *,
    run_id: str = "",
    tool_call_id: str = "",
) -> Optional[Dict[str, Any]]:
    if _contains_secret(result_text):
        return _decision(
            tool_name,
            "medium",
            "warn",
            "Tool output appears to contain a secret-like token",
            False,
            tool_call_id,
            run_id,
        )

    edit = metadata.get("file_edit") if isinstance(metadata, dict) else None
    if edit and (edit.get("stats", {}).get("added", 0) + edit.get("stats", {}).get("removed", 0) > 1200):
        return _decision(
            tool_name,
            "medium",
            "warn",
            "Large file edit detected; review diff carefully",
            False,
            tool_call_id,
            run_id,
        )
    return None
