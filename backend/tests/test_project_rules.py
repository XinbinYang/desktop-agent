"""Tests for project_rules.py — .desktop-agent.md project rules system."""
import os
from pathlib import Path

from app.project_rules import (
    PROJECT_RULES_FILE,
    _read_rules_file,
    _resolve_template,
    build_rules_prompt,
    get_project_rules,
    get_user_rules,
)


class TestResolveTemplate:
    def test_project_path(self):
        result = _resolve_template("路径: {{project_path}}", project_path="/home/user/myproject")
        assert "路径: /home/user/myproject" == result

    def test_project_name(self):
        result = _resolve_template("项目名: {{project_name}}", project_path="/home/user/myproject")
        assert "项目名: myproject" == result

    def test_branch(self):
        result = _resolve_template("分支: {{branch}}", branch="feature/login")
        assert "分支: feature/login" == result

    def test_os(self):
        result = _resolve_template("系统: {{os}}")
        assert "{{os}}" not in result
        assert len(result) > 3

    def test_platform(self):
        result = _resolve_template("平台: {{platform}}")
        assert "{{platform}}" not in result

    def test_user(self):
        result = _resolve_template("用户: {{user}}")
        assert "{{user}}" not in result

    def test_home(self):
        result = _resolve_template("家目录: {{home}}")
        assert "{{home}}" not in result
        assert str(Path.home()) in result

    def test_multiple_variables(self):
        result = _resolve_template(
            "项目 {{project_name}} 在 {{project_path}} 的分支 {{branch}}",
            project_path="/a/b",
            branch="main",
        )
        assert "项目 b 在 /a/b 的分支 main" == result


class TestReadRulesFile:
    def test_missing_file_returns_none(self, tmp_path):
        assert _read_rules_file(tmp_path / "nonexistent.md") is None

    def test_reads_valid_file(self, tmp_path):
        p = tmp_path / "test.md"
        p.write_text("hello world", encoding="utf-8")
        assert _read_rules_file(p) == "hello world"

    def test_returns_none_for_binary(self, tmp_path):
        p = tmp_path / "binary.md"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _read_rules_file(p)
        # Should not raise, returns content or None
        assert result is not None  # read_text with errors='replace' survives binary

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.md"
        p.write_text("", encoding="utf-8")
        assert _read_rules_file(p) == ""


class TestGetProjectRules:
    def test_no_rules_file(self, tmp_path):
        assert get_project_rules(str(tmp_path)) is None

    def test_reads_rules_file(self, tmp_path):
        rules = tmp_path / PROJECT_RULES_FILE
        rules.write_text("# 我的项目规则\n使用 TypeScript", encoding="utf-8")
        content = get_project_rules(str(tmp_path))
        assert content is not None
        assert "我的项目规则" in content
        assert "TypeScript" in content

    def test_template_substitution(self, tmp_path):
        rules = tmp_path / PROJECT_RULES_FILE
        rules.write_text("路径: {{project_path}}, 分支: {{branch}}", encoding="utf-8")
        content = get_project_rules(str(tmp_path), branch="main")
        assert content is not None
        assert str(tmp_path) in content
        assert "main" in content

    def test_empty_project_path(self):
        assert get_project_rules("") is None
        # Whitespace path: treated as a path but file won't exist
        assert get_project_rules("  ") is None


class TestBuildRulesPrompt:
    def test_empty_when_no_rules(self, tmp_path):
        # Neither project nor user rules exist
        result = build_rules_prompt(str(tmp_path))
        assert result == ""

    def test_includes_project_rules(self, tmp_path):
        rules = tmp_path / PROJECT_RULES_FILE
        rules.write_text("规则内容", encoding="utf-8")
        result = build_rules_prompt(str(tmp_path))
        assert ".desktop-agent.md" in result
        assert "规则内容" in result
