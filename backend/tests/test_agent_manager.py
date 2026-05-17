"""Test AgentManager — dual-agent prompt rendering, workspace files, backward compat."""

import pytest
from pathlib import Path
from app.agents.manager import AgentManager, _truncate


class TestAgentManagerPromptRendering:
    """Verify that AgentManager assembles correct prompts for both agent types."""

    def test_render_personal_prompt_contains_key_files(self):
        prompt = AgentManager.render_prompt("personal", "TOOLS_DESC_HERE")
        # Personal prompt must contain the core persona files
        assert "Personal Agent" in prompt or "运行规范" in prompt  # AGENTS.md
        assert "SOUL.md" in prompt or "人格核心" in prompt or "Core Truths" in prompt

    def test_render_coding_prompt_contains_key_files(self):
        prompt = AgentManager.render_prompt("coding", "TOOLS_DESC_HERE")
        # Coding prompt must contain strict AGENTS.md
        assert "执行底座" in prompt or "Coding Agent" in prompt

    def test_coding_prompt_excludes_personal_files(self):
        """Coding Agent must NOT inject personal-only files like INNER.md"""
        prompt = AgentManager.render_prompt("coding", "TOOLS_DESC_HERE")
        assert "内在世界" not in prompt
        assert "IDENTITY.md" not in prompt

    def test_personal_prompt_includes_shared_files(self):
        prompt = AgentManager.render_prompt("personal", "TOOLS_DESC_HERE")
        assert "base_rules" in prompt.lower() or "运行环境锚定" in prompt

    def test_missing_workspace_file_does_not_crash(self, monkeypatch, tmp_path):
        """If a workspace file is missing, rendering must not crash."""
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        prompt = AgentManager.render_prompt("personal", "TOOLS")
        assert len(prompt) > 0  # Must produce something

    def test_bootstrap_injection(self, tmp_path, monkeypatch):
        """When BOOTSTRAP.md exists, it must be injected at highest priority."""
        personal_dir = tmp_path / "personal"
        personal_dir.mkdir(parents=True)
        (personal_dir / "BOOTSTRAP.md").write_text("# BOOTSTRAP CONTENT HERE", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)

        prompt = AgentManager.render_prompt("personal", "TOOLS")
        # Bootstrap content should appear before AGENTS.md content
        assert "BOOTSTRAP CONTENT HERE" in prompt

    def test_empty_user_md_triggers_bootstrap_hint(self, tmp_path, monkeypatch):
        """When USER.md contains template placeholders, a bootstrap hint is appended."""
        personal_dir = tmp_path / "personal"
        personal_dir.mkdir(parents=True)
        (personal_dir / "USER.md").write_text("- **称呼**: （请填写你的名字或昵称）", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)

        prompt = AgentManager.render_prompt("personal", "TOOLS")
        assert "引导提示" in prompt


class TestAgentManagerBackwardCompat:
    """Verify backward-compatible role_id → agent_type mapping."""

    def test_desktop_agent_maps_to_personal(self):
        assert AgentManager.get_agent_type_for_role("desktop-agent") == "personal"

    def test_code_expert_maps_to_coding(self):
        assert AgentManager.get_agent_type_for_role("code-expert") == "coding"

    def test_general_assistant_maps_to_personal(self):
        assert AgentManager.get_agent_type_for_role("general-assistant") == "personal"

    def test_quant_analyst_maps_to_personal(self):
        assert AgentManager.get_agent_type_for_role("quant-analyst") == "personal"

    def test_unknown_role_falls_back_to_personal(self):
        assert AgentManager.get_agent_type_for_role("nonexistent-role") == "personal"

    def test_get_default_role(self):
        assert AgentManager.get_default_role("personal") == "desktop-agent"
        assert AgentManager.get_default_role("coding") == "code-expert"


class TestAgentManagerWorkspaceFiles:
    """Verify workspace file CRUD operations."""

    def test_save_and_load_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        ok = AgentManager.save_workspace_file("personal", "test.md", "hello world")
        assert ok
        content = AgentManager.load_workspace_file("personal", "test.md")
        assert content == "hello world"

    def test_list_workspace_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        AgentManager.save_workspace_file("personal", "a.md", "aaa")
        AgentManager.save_workspace_file("personal", "b.md", "bbb")
        files = AgentManager.list_workspace_files("personal")
        names = {f["name"] for f in files}
        assert "a.md" in names
        assert "b.md" in names

    def test_list_agents(self):
        agents = AgentManager.list_agents()
        assert len(agents) == 2
        types = {a["type"] for a in agents}
        assert types == {"personal", "coding"}


class TestBootstrapManagement:
    """Verify bootstrap lifecycle."""

    def test_is_bootstrapped_without_bootstrap_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        assert AgentManager.is_bootstrapped() is True  # No BOOTSTRAP.md → bootstrapped

    def test_is_bootstrapped_false_when_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        (tmp_path / "personal").mkdir(parents=True)
        (tmp_path / "personal" / "BOOTSTRAP.md").write_text("test", encoding="utf-8")
        assert AgentManager.is_bootstrapped() is False

    def test_reset_bootstrap_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        assert AgentManager.reset_bootstrap() is True
        assert (tmp_path / "personal" / "BOOTSTRAP.md").exists()
        assert AgentManager.is_bootstrapped() is False

    def test_reset_bootstrap_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        AgentManager.reset_bootstrap()
        AgentManager.reset_bootstrap()
        assert (tmp_path / "personal" / "BOOTSTRAP.md").exists()


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated_at_newline(self):
        text = "line one\nline two\nline three"
        result = _truncate(text, 20)
        assert len(result) <= 20
