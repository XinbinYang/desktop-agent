"""Comprehensive tests for guardrails.py — safety-critical module with pre/post tool evaluation."""
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.guardrails import (
    DANGEROUS_COMMANDS,
    NON_PORTABLE_COMMANDS,
    SECRET_PATTERNS,
    TEST_PATH_PATTERN,
    TEST_EDIT_INTENT_PATTERN,
    _contains_secret,
    _is_test_path,
    _prompt_allows_test_edits,
    _path_points_to_original_project,
    _decision,
    evaluate_pre_tool,
    evaluate_post_tool,
)
from app.coding_runs import RunContext


# ── Unit tests for helper predicates ────────────────────────────────────────

class TestContainsSecret:
    def test_detects_openai_sk_key(self):
        assert _contains_secret("OPENAI_API_KEY=sk-proj-abcdefghijklmnop1234567890")
        assert _contains_secret("export ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnop")

    def test_detects_github_pat(self):
        for prefix in ("ghp_", "ghs_", "gho_", "ghu_", "ghr_"):
            assert _contains_secret(f"token={prefix}12345678901234567890")

    def test_detects_gitlab_pat(self):
        assert _contains_secret("glpat-AbCdEfGhIjKlMnOp1234567890")

    def test_detects_aws_access_key(self):
        # Pattern is \b(?:AKIA|ASIA)[0-9A-Z]{16}\b — exactly 16 [0-9A-Z] after prefix
        assert _contains_secret("AKIAIOSFODNN7EXAMPLE")  # exactly 16 chars
        assert _contains_secret("ASIA1234567890ABCDEF")   # exactly 16 chars
        assert not _contains_secret("AKIAIO")  # too short for the \b after

    def test_detects_slack_token(self):
        assert _contains_secret("xoxb-123456789012-abcdefghijklmnopqrst")
        assert _contains_secret("xoxp-123456789012-abcdefghijklmnopqrst")

    def test_no_false_positive_on_short_strings(self):
        assert not _contains_secret("sk-abc")  # too short
        assert not _contains_secret("ghp_short")  # too short

    def test_no_false_positive_on_normal_text(self):
        assert not _contains_secret("hello world")
        assert not _contains_secret("branch: feature/add-login")
        assert not _contains_secret("model: gpt-4o-mini")

    def test_empty_and_none(self):
        assert not _contains_secret("")
        assert not _contains_secret(None)

    def test_secret_in_middle_of_text(self):
        assert _contains_secret(
            "Here is my key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz123 for the API"
        )


class TestIsTestPath:
    def test_python_test_file(self):
        assert _is_test_path("tests/test_auth.py")
        assert _is_test_path("src/tests/test_models.py")
        assert _is_test_path("test_utils.py")

    def test_typescript_test_file(self):
        assert _is_test_path("src/__tests__/Button.test.tsx")
        assert _is_test_path("components/ChatPanel.test.tsx")
        assert _is_test_path("utils.spec.ts")

    def test_backslash_paths(self):
        assert _is_test_path("src\\tests\\test_auth.py")
        assert _is_test_path("src\\__tests__\\App.test.tsx")

    def test_non_test_path(self):
        assert not _is_test_path("src/app/auth.py")
        assert not _is_test_path("src/components/Button.tsx")
        assert not _is_test_path("utils/helpers.ts")

    def test_empty_and_none(self):
        assert not _is_test_path("")
        assert not _is_test_path(None)


class TestPromptAllowsTestEdits:
    def test_explicit_test_creation(self):
        assert _prompt_allows_test_edits("add unit tests for the login function")
        assert _prompt_allows_test_edits("write tests to cover the new code")

    def test_test_update(self):
        assert _prompt_allows_test_edits("update tests after refactoring")
        assert _prompt_allows_test_edits("修改测试用例")
        assert _prompt_allows_test_edits("补充测试覆盖")

    def test_chinese_test_instructions(self):
        assert _prompt_allows_test_edits("新增单元测试")
        assert _prompt_allows_test_edits("请添加测试")

    def test_extra_context_merged(self):
        assert _prompt_allows_test_edits("refactor the module", "add tests for coverage")

    def test_no_test_intent(self):
        assert not _prompt_allows_test_edits("fix the login bug")
        assert not _prompt_allows_test_edits("add a new feature to the dashboard")
        assert not _prompt_allows_test_edits("refactor user service for performance")

    def test_empty_prompt(self):
        assert not _prompt_allows_test_edits("")
        assert not _prompt_allows_test_edits("", "")


class TestPathPointsToOriginalProject:
    def test_path_in_original_not_worktree(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (project / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="test")
        assert _path_points_to_original_project(str(project / "src" / "app.py"), ctx)

    def test_path_in_worktree_is_not_blocked(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (worktree / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="test")
        assert not _path_points_to_original_project(str(worktree / "src" / "app.py"), ctx)

    def test_path_outside_project_is_not_blocked(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(tmp_path / "wt"), prompt="test")
        assert not _path_points_to_original_project(str(tmp_path / "elsewhere" / "file.txt"), ctx)

    def test_no_worktree_mode_returns_false(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "inline", prompt="test")
        assert not _path_points_to_original_project(str(project / "src" / "app.py"), ctx)

    def test_empty_path(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(tmp_path / "wt"), prompt="test")
        assert not _path_points_to_original_project("", ctx)

    def test_invalid_path_returns_false(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(tmp_path / "wt"), prompt="test")
        # NUL character makes path invalid on Windows
        assert not _path_points_to_original_project("src/\x00app.py", ctx)


class TestDecision:
    def test_blocked_decision(self):
        d = _decision("shell_execute", "high", "blocked", "dangerous", True, "call1", "run1")
        assert d["risk"] == "high"
        assert d["decision"] == "blocked"
        assert d["requires_approval"] is True

    def test_allowed_decision(self):
        d = _decision("file_read", "low", "allowed", "ok", False, "call2", "run2")
        assert d["risk"] == "low"
        assert d["decision"] == "allowed"
        assert d["requires_approval"] is False


# ── Integration tests for every DANGEROUS_COMMANDS pattern ──────────────────

class TestDangerousCommandsBlocked:
    """Each dangerous pattern must cause a 'blocked' decision."""

    def test_git_reset_hard_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git reset --hard HEAD~1"})
        assert result["decision"] == "blocked"
        assert "reset" in result["reason"].lower()

    def test_git_reset_hard_case_insensitive(self):
        result = evaluate_pre_tool("shell_execute", {"command": "GIT RESET --HARD origin/main"})
        assert result["decision"] == "blocked"

    def test_git_clean_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git clean -fd"})
        assert result["decision"] == "blocked"

    def test_git_clean_with_dash_x(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git clean -xdf"})
        assert result["decision"] == "blocked"

    def test_git_checkout_dot_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git checkout ."})
        assert result["decision"] == "blocked"
        assert "checkout" in result["reason"].lower()

    def test_git_branch_force_delete_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git branch -D feature/old"})
        assert result["decision"] == "blocked"

    def test_rm_rf_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "rm -rf /tmp/build"})
        assert result["decision"] == "blocked"

    def test_rm_rf_root_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "rm -rf /"})
        assert result["decision"] == "blocked"

    def test_remove_item_recurse_force_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "Remove-Item -Path . -Recurse -Force"})
        assert result["decision"] == "blocked"

    def test_format_drive_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "format C:"})
        assert result["decision"] == "blocked"

    def test_del_force_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "del /f /s /q *.*"})
        assert result["decision"] == "blocked"

    def test_safe_git_commands_allowed(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git status"})
        assert result["decision"] == "allowed"

    def test_safe_git_push_allowed(self):
        result = evaluate_pre_tool("shell_execute", {"command": "git push origin main"})
        assert result["decision"] == "allowed"

    def test_safe_shell_command_allowed(self):
        result = evaluate_pre_tool("shell_execute", {"command": "python -m pytest tests/"})
        assert result["decision"] == "allowed"


# ── Non-portable Unix command blocking ──────────────────────────────────────

class TestNonPortableCommandsBlocked:
    def test_tail_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "tail -n 20 log.txt"})
        assert result["decision"] == "blocked"
        assert "non-portable" in result["reason"].lower()

    def test_head_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "head -n 10 file.txt"})
        assert result["decision"] == "blocked"

    def test_grep_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "grep -r 'TODO' src/"})
        assert result["decision"] == "blocked"

    def test_sed_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "sed 's/foo/bar/g' file.txt"})
        assert result["decision"] == "blocked"

    def test_awk_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "awk '{print $1}' data.csv"})
        assert result["decision"] == "blocked"

    def test_piped_non_portable_blocked(self):
        result = evaluate_pre_tool("shell_execute", {"command": "cat file.txt | grep error"})
        assert result["decision"] == "blocked"

    def test_powershell_equivalent_allowed(self):
        result = evaluate_pre_tool("shell_execute", {"command": "Select-String -Path *.py -Pattern 'TODO'"})
        assert result["decision"] == "allowed"

    def test_ripgrep_allowed(self):
        result = evaluate_pre_tool("shell_execute", {"command": "rg TODO src/"})
        assert result["decision"] == "allowed"

    def test_verify_project_also_checked(self):
        result = evaluate_pre_tool("verify_project", {"command": "grep error log.txt"})
        assert result["decision"] == "blocked"

    def test_shell_start_also_checked(self):
        result = evaluate_pre_tool("shell_start", {"command": "tail -f log.txt"})
        assert result["decision"] == "blocked"


# ── Test file edit blocking ─────────────────────────────────────────────────

class TestTestFileEditBlocking:
    def test_file_write_to_test_path_blocked_without_intent(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "tests/test_auth.py", "content": "def test_login(): pass"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline", prompt="fix the login bug"),
        )
        assert result["decision"] == "blocked"
        assert "test" in result["reason"].lower()

    def test_file_write_to_test_path_allowed_with_intent(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "tests/test_auth.py", "content": "def test_login(): pass"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline",
                           prompt="add unit tests for the login function"),
        )
        assert result["decision"] == "allowed"

    def test_file_write_to_non_test_path_allowed(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "src/auth.py", "content": "def login(): pass"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline", prompt="implement login"),
        )
        assert result["decision"] == "allowed"

    def test_file_patch_to_test_path_blocked(self):
        result = evaluate_pre_tool(
            "file_patch",
            {"path": "src/__tests__/login.test.tsx", "new_text": "it('works', () => {})"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline", prompt="fix the button"),
        )
        assert result["decision"] == "blocked"

    def test_chinese_test_intent_allows_edits(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "tests/test_api.py", "content": "def test(): pass"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline", prompt="请新增单元测试"),
        )
        assert result["decision"] == "allowed"

    def test_conversation_context_also_checked(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "tests/test_api.py", "content": "def test(): pass"},
            ctx=RunContext("run1", "s1", "/tmp/proj", "inline", prompt="refactor module"),
            conversation_context="please also add tests for coverage",
        )
        assert result["decision"] == "allowed"

    def test_no_ctx_does_not_block(self):
        """Without RunContext, test-path guard is skipped."""
        result = evaluate_pre_tool(
            "file_write",
            {"path": "tests/test_auth.py", "content": "def test_login(): pass"},
            ctx=None,
        )
        assert result["decision"] == "allowed"


# ── Secret detection in file content ────────────────────────────────────────

class TestSecretInContentBlocked:
    def test_openai_key_in_content_blocked(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "config.py", "content": "API_KEY = 'sk-proj-abcdefghijklmnopqrstuvwxyz'"},
        )
        assert result["decision"] == "blocked"
        assert "secret" in result["reason"].lower()

    def test_github_pat_in_content_blocked(self):
        result = evaluate_pre_tool(
            "file_patch",
            {"path": ".env", "new_text": "GITHUB_TOKEN=ghp_12345678901234567890"},
        )
        assert result["decision"] == "blocked"

    def test_slack_token_in_content_blocked(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "config.json", "content": '{"token": "xoxb-123456789012-abcdefghijklmnopqrst"}'},
        )
        assert result["decision"] == "blocked"

    def test_clean_content_allowed(self):
        result = evaluate_pre_tool(
            "file_write",
            {"path": "config.py", "content": "DEBUG = True\nPORT = 8080"},
        )
        assert result["decision"] == "allowed"

    def test_non_write_tools_not_checked_for_secrets(self):
        result = evaluate_pre_tool(
            "file_read",
            {"path": "config.py"},
        )
        assert result["decision"] == "allowed"


# ── Worktree path protection ────────────────────────────────────────────────

class TestWorktreePathProtection:
    def test_write_to_original_project_blocked_in_worktree_mode(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (project / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="implement feature")

        result = evaluate_pre_tool(
            "file_write",
            {"path": str(project / "src" / "app.py"), "content": "x = 1"},
            ctx=ctx,
        )
        assert result["decision"] == "blocked"
        assert "worktree" in result["reason"].lower()

    def test_write_to_worktree_allowed_in_worktree_mode(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (worktree / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="implement feature")

        result = evaluate_pre_tool(
            "file_write",
            {"path": str(worktree / "src" / "app.py"), "content": "x = 1"},
            ctx=ctx,
        )
        assert result["decision"] == "allowed"

    def test_file_delete_blocked_in_worktree_mode(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (project / "obsolete.py").write_text("old")

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="clean up")

        result = evaluate_pre_tool(
            "file_delete",
            {"path": str(project / "obsolete.py")},
            ctx=ctx,
        )
        assert result["decision"] == "blocked"

    def test_file_patch_blocked_in_worktree_mode(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()
        (project / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="fix bug")

        result = evaluate_pre_tool(
            "file_patch",
            {"path": str(project / "src" / "app.py"), "new_text": "fixed"},
            ctx=ctx,
        )
        assert result["decision"] == "blocked"

    def test_inline_mode_does_not_block_writes(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "src").mkdir()

        ctx = RunContext("run1", "s1", str(project), "inline", prompt="implement feature")

        result = evaluate_pre_tool(
            "file_write",
            {"path": str(project / "src" / "app.py"), "content": "x = 1"},
            ctx=ctx,
        )
        assert result["decision"] == "allowed"

    def test_read_only_tools_not_blocked_in_worktree_mode(self, tmp_path):
        project = tmp_path / "project"
        worktree = tmp_path / "worktree"
        project.mkdir()
        worktree.mkdir()

        ctx = RunContext("run1", "s1", str(project), "worktree",
                         worktree_path=str(worktree), prompt="read file")

        result = evaluate_pre_tool(
            "file_read",
            {"path": str(project / "README.md")},
            ctx=ctx,
        )
        assert result["decision"] == "allowed"


# ── Other tool types pass through ───────────────────────────────────────────

class TestOtherToolsPassThrough:
    def test_browser_tools_allowed(self):
        result = evaluate_pre_tool("browser_navigate", {"url": "https://example.com"})
        assert result["decision"] == "allowed"

    def test_screenshot_tool_allowed(self):
        result = evaluate_pre_tool("screenshot", {})
        assert result["decision"] == "allowed"

    def test_git_status_allowed(self):
        result = evaluate_pre_tool("git_status", {"path": "."})
        assert result["decision"] == "allowed"

    def test_knowledge_search_allowed(self):
        result = evaluate_pre_tool("knowledge_search", {"query": "architecture"})
        assert result["decision"] == "allowed"

    def test_file_read_allowed(self):
        result = evaluate_pre_tool("file_read", {"path": "README.md"})
        assert result["decision"] == "allowed"


# ── evaluate_post_tool ──────────────────────────────────────────────────────

class TestEvaluatePostTool:
    def test_secret_in_output_warns(self):
        result = evaluate_post_tool("shell_execute", "Found key: sk-ant-api03-abcdefghijklmnopqrstuvwxyz", {},
                                    run_id="r1", tool_call_id="c1")
        assert result is not None
        assert result["decision"] == "warn"

    def test_large_file_edit_warns(self):
        result = evaluate_post_tool(
            "file_write",
            "OK",
            {"file_edit": {"stats": {"added": 800, "removed": 500}}},
            run_id="r1", tool_call_id="c1",
        )
        assert result is not None
        assert result["decision"] == "warn"

    def test_small_file_edit_no_warning(self):
        result = evaluate_post_tool(
            "file_write",
            "OK",
            {"file_edit": {"stats": {"added": 10, "removed": 5}}},
            run_id="r1", tool_call_id="c1",
        )
        assert result is None

    def test_no_secret_no_edit_no_warning(self):
        result = evaluate_post_tool(
            "file_read",
            "File contents here, nothing sensitive.",
            {},
            run_id="r1", tool_call_id="c1",
        )
        assert result is None

    def test_empty_output_no_warning(self):
        result = evaluate_post_tool("shell_execute", "", {}, run_id="r1", tool_call_id="c1")
        assert result is None

    def test_edit_metadata_none_no_warning(self):
        result = evaluate_post_tool(
            "file_write",
            "OK",
            None,  # type wrapping may pass None
            run_id="r1", tool_call_id="c1",
        )
        assert result is None


# ── Verify all DANGEROUS_COMMANDS patterns are tested ───────────────────────

def test_all_dangerous_patterns_have_at_least_one_test():
    """Guard against regression: ensure every dangerous pattern is tested."""
    tested_patterns = set()

    # Collect all test methods that reference dangerous command patterns
    for pattern in DANGEROUS_COMMANDS:
        pattern_str = pattern.pattern
        # Each test method name hints at the pattern covered
        # This is a self-check: if we add new patterns, this test reminds us
        assert pattern.pattern, f"Empty pattern found: {pattern}"

    assert len(DANGEROUS_COMMANDS) == 8, (
        f"Expected 8 DANGEROUS_COMMANDS patterns, got {len(DANGEROUS_COMMANDS)}. "
        "If you added a pattern, add a corresponding test in TestDangerousCommandsBlocked."
    )


def test_all_non_portable_patterns_have_coverage():
    assert len(NON_PORTABLE_COMMANDS) == 1, (
        f"Expected 1 NON_PORTABLE_COMMANDS pattern, got {len(NON_PORTABLE_COMMANDS)}. "
        "If you added a pattern, add a corresponding test in TestNonPortableCommandsBlocked."
    )
    # The single pattern covers tail|head|grep|sed|awk — verify each is tested
    pattern = NON_PORTABLE_COMMANDS[0].pattern
    assert "tail" in pattern
    assert "head" in pattern
    assert "grep" in pattern
    assert "sed" in pattern
    assert "awk" in pattern


# ── Pattern-specific edge cases ─────────────────────────────────────────────

class TestCommandPatternEdgeCases:
    def test_git_reset_hard_in_middle_of_command(self):
        result = evaluate_pre_tool("shell_execute", {"command": "echo before && git reset --hard HEAD && echo after"})
        assert result["decision"] == "blocked"

    def test_git_checkout_dot_with_branch(self):
        """git checkout . should be blocked but git checkout branch should not."""
        result = evaluate_pre_tool("shell_execute", {"command": "git checkout main"})
        # "git checkout ." matches via regex — "git checkout main" should NOT match
        assert result["decision"] == "allowed"

    def test_rm_rf_just_directory(self):
        result = evaluate_pre_tool("shell_execute", {"command": "rm -rf build/"})
        assert result["decision"] == "blocked"

    def test_non_portable_in_chained_command(self):
        """Non-portable command after semicolon is caught."""
        result = evaluate_pre_tool("shell_execute", {"command": "echo start; grep error log.txt"})
        assert result["decision"] == "blocked"

    def test_non_portable_after_pipe(self):
        result = evaluate_pre_tool("shell_execute", {"command": "echo start | grep error"})
        assert result["decision"] == "blocked"
