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

    def test_personal_session_prompt_does_not_inject_current_project(self, tmp_path, monkeypatch, isolate_projects):
        """Personal is global/runtime-scoped even when the UI has an open project."""
        from app.agent import AgentSession
        from app.config import get_model_for_agent
        from app.project_manager import ProjectManager

        agents_root = tmp_path / "AGENTS"
        (agents_root / "personal" / "WORKSPACE").mkdir(parents=True)
        (agents_root / "_shared").mkdir(parents=True)
        (agents_root / "personal" / "AGENTS.md").write_text("Personal Agent rules", encoding="utf-8")
        (agents_root / "personal" / "WORKSPACE" / "SOUL.md").write_text("Personal Agent soul", encoding="utf-8")
        (agents_root / "_shared" / "base_rules.md").write_text("Shared non-project rules", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", agents_root)

        project = tmp_path / "opened-project"
        project.mkdir()
        (project / ".desktop-agent.md").write_text("PROJECT_RULE_SENTINEL", encoding="utf-8")
        ProjectManager._current_project = {"path": str(project), "name": "opened-project"}

        session = AgentSession(model_id=get_model_for_agent("personal"), session_id="personal-no-project", agent_type="personal")
        session._last_user_message = "hello"
        prompt = session._build_system_prompt()

        assert "## Current Project" not in prompt
        assert str(project) not in prompt
        assert "PROJECT_RULE_SENTINEL" not in prompt

    def test_coding_session_prompt_injects_bound_project(self, tmp_path, monkeypatch, isolate_projects):
        from app.agent import AgentSession
        from app.config import get_model_for_agent

        agents_root = tmp_path / "AGENTS"
        (agents_root / "coding").mkdir(parents=True)
        (agents_root / "_shared").mkdir(parents=True)
        (agents_root / "coding" / "AGENTS.md").write_text("Coding Agent rules", encoding="utf-8")
        (agents_root / "coding" / "SOUL.md").write_text("Coding Agent soul", encoding="utf-8")
        (agents_root / "_shared" / "base_rules.md").write_text("Shared rules", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", agents_root)

        project = tmp_path / "bound-project"
        project.mkdir()

        session = AgentSession(model_id=get_model_for_agent("coding"), session_id="coding-bound-project", agent_type="coding")
        session.project_path = str(project)
        session._last_user_message = "inspect project"
        prompt = session._build_system_prompt()

        assert "## Current Project" in prompt
        assert str(project) in prompt

    def test_missing_workspace_file_does_not_crash(self, monkeypatch, tmp_path):
        """If a workspace file is missing, rendering must not crash."""
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        prompt = AgentManager.render_prompt("personal", "TOOLS")
        assert len(prompt) > 0  # Must produce something

    def test_bootstrap_injection(self, tmp_path, monkeypatch):
        """When BOOTSTRAP.md exists, it must be injected at highest priority."""
        personal_dir = tmp_path / "personal" / "WORKSPACE"
        personal_dir.mkdir(parents=True)
        (personal_dir / "BOOTSTRAP.md").write_text("# BOOTSTRAP CONTENT HERE", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)

        prompt = AgentManager.render_prompt("personal", "TOOLS")
        # Bootstrap content should appear before AGENTS.md content
        assert "BOOTSTRAP CONTENT HERE" in prompt

    def test_empty_user_md_triggers_bootstrap_hint(self, tmp_path, monkeypatch):
        """When USER.md contains template placeholders, a bootstrap hint is appended."""
        personal_dir = tmp_path / "personal" / "WORKSPACE"
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

    def test_runtime_agents_seed_from_bundled_templates(self, tmp_path, monkeypatch):
        from app import runtime_paths

        bundle = tmp_path / "bundle"
        template_file = bundle / "AGENTS" / "personal" / "WORKSPACE" / "USER.md"
        template_file.parent.mkdir(parents=True)
        template_file.write_text("seed user", encoding="utf-8")
        (bundle / "AGENTS" / "personal" / "WORKSPACE" / "BOOTSTRAP.md").write_text("seed bootstrap", encoding="utf-8")
        (bundle / "AGENTS" / "personal" / "AGENTS.md").write_text("protected rules", encoding="utf-8")
        user_data = tmp_path / "user-data"

        monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(user_data))
        monkeypatch.setattr(runtime_paths, "bundled_root", lambda: bundle)
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", None)

        root = AgentManager._agents_root()
        runtime_file = root / "personal" / "WORKSPACE" / "USER.md"
        runtime_bootstrap = root / "personal" / "WORKSPACE" / "BOOTSTRAP.md"
        assert root == user_data / "backend" / "AGENTS"
        assert (root / "personal" / "AGENTS.md").read_text(encoding="utf-8") == "protected rules"
        assert runtime_file.read_text(encoding="utf-8") == "seed user"
        assert runtime_bootstrap.read_text(encoding="utf-8") == "seed bootstrap"

        runtime_file.write_text("custom user", encoding="utf-8")
        runtime_bootstrap.unlink()
        assert AgentManager._agents_root().joinpath("personal", "WORKSPACE", "USER.md").read_text(encoding="utf-8") == "custom user"
        assert not AgentManager._agents_root().joinpath("personal", "WORKSPACE", "BOOTSTRAP.md").exists()

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

    def test_shared_preferences_logical_file_maps_to_shared_workspace(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)

        ok = AgentManager.save_workspace_file("_shared", "user_preferences.md", "prefs")

        assert ok
        assert (tmp_path / "_shared" / "WORKSPACE" / "user_preferences.md").read_text(encoding="utf-8") == "prefs"
        assert AgentManager.load_workspace_file("_shared", "user_preferences.md") == "prefs"

    def test_list_agents(self):
        agents = AgentManager.list_agents()
        assert len(agents) == 2
        types = {a["type"] for a in agents}
        assert types == {"personal", "coding"}

    def test_agents_files_api_reads_runtime_workspace(self, client, tmp_path, monkeypatch):
        runtime_agents = tmp_path / "AGENTS"
        personal = runtime_agents / "personal" / "WORKSPACE"
        personal.mkdir(parents=True)
        (personal / "USER.md").write_text("runtime user profile", encoding="utf-8")
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", runtime_agents)

        response = client.get("/api/agents/personal/files/USER.md")

        assert response.status_code == 200
        assert response.json()["content"] == "runtime user profile"

    def test_runtime_agent_home_migration_rewrites_exact_legacy_text(self, tmp_path):
        from app import runtime_paths

        runtime_agents = tmp_path / "AGENTS"
        shared = runtime_agents / "_shared"
        personal = runtime_agents / "personal"
        shared.mkdir(parents=True)
        personal.mkdir(parents=True)
        (shared / "base_rules.md").write_text(
            "## 运行环境锚定\n\n"
            "- 你当前就运行在本项目（`desktop-agent`）的代码库中。工作目录即项目根目录。\n"
            "- **禁止主动克隆外部仓库、搜索外部模板、或访问与当前任务无关的外部资源。**\n"
            "- 只有当用户**明确要求**时，才使用 `git_clone` 或访问外部网站（`browser_navigate`）。\n"
            "- 用户让你\"熟悉代码库\"\"了解项目\"时，应直接读取当前目录下的文件，而不是去外部搜索。\n\n"
            "CUSTOM_SHARED_LINE\n",
            encoding="utf-8",
        )
        (personal / "AGENTS.md").write_text(
            "> - 工作区根 = 项目仓库根目录（即 `desktop-agent` 所在的目录）。\n"
            "> - 你的身份与记忆文件统一位于运行时 `AGENTS/personal/`。\n"
            "CUSTOM_PERSONAL_LINE\n",
            encoding="utf-8",
        )

        runtime_paths._migrate_agent_home_context(runtime_agents)

        shared_text = (shared / "base_rules.md").read_text(encoding="utf-8")
        personal_text = (personal / "AGENTS.md").read_text(encoding="utf-8")
        assert "你当前就运行在本项目" not in shared_text
        assert "项目仓库根目录" not in personal_text
        assert "CUSTOM_SHARED_LINE" in shared_text
        assert "CUSTOM_PERSONAL_LINE" in personal_text
        assert any(tmp_path.glob("AGENTS-personal-home-migration-*"))

    def test_personal_workspace_layout_migration_moves_mutable_files(self, tmp_path):
        from app import runtime_paths

        runtime_agents = tmp_path / "AGENTS"
        personal = runtime_agents / "personal"
        shared = runtime_agents / "_shared"
        (personal / "memory").mkdir(parents=True)
        (personal / "skills").mkdir()
        shared.mkdir(parents=True)
        (personal / "AGENTS.md").write_text("protected personal rules", encoding="utf-8")
        (personal / "SOUL.md").write_text("old soul", encoding="utf-8")
        (personal / "USER.md").write_text("old user", encoding="utf-8")
        (personal / "memory" / "day.md").write_text("diary", encoding="utf-8")
        (personal / "skills" / "one.md").write_text("skill", encoding="utf-8")
        (shared / "base_rules.md").write_text("protected shared rules", encoding="utf-8")
        (shared / "user_preferences.md").write_text("prefs", encoding="utf-8")

        runtime_paths._migrate_personal_workspace_layout(runtime_agents)

        workspace = personal / "WORKSPACE"
        shared_workspace = shared / "WORKSPACE"
        assert (personal / "AGENTS.md").read_text(encoding="utf-8") == "protected personal rules"
        assert (shared / "base_rules.md").read_text(encoding="utf-8") == "protected shared rules"
        assert (workspace / "SOUL.md").read_text(encoding="utf-8") == "old soul"
        assert (workspace / "USER.md").read_text(encoding="utf-8") == "old user"
        assert (workspace / "memory" / "day.md").read_text(encoding="utf-8") == "diary"
        assert (workspace / "skills" / "one.md").read_text(encoding="utf-8") == "skill"
        assert (shared_workspace / "user_preferences.md").read_text(encoding="utf-8") == "prefs"
        assert (runtime_agents / ".personal-workspace-migration-v1").exists()


class TestBootstrapManagement:
    """Verify bootstrap lifecycle."""

    def test_is_bootstrapped_without_bootstrap_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        assert AgentManager.is_bootstrapped() is True  # No BOOTSTRAP.md → bootstrapped

    def test_is_bootstrapped_false_when_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        (tmp_path / "personal" / "WORKSPACE").mkdir(parents=True)
        (tmp_path / "personal" / "WORKSPACE" / "BOOTSTRAP.md").write_text("test", encoding="utf-8")
        assert AgentManager.is_bootstrapped() is False

    def test_reset_bootstrap_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        assert AgentManager.reset_bootstrap() is True
        assert (tmp_path / "personal" / "WORKSPACE" / "BOOTSTRAP.md").exists()
        assert AgentManager.is_bootstrapped() is False

    def test_reset_bootstrap_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        AgentManager.reset_bootstrap()
        AgentManager.reset_bootstrap()
        assert (tmp_path / "personal" / "WORKSPACE" / "BOOTSTRAP.md").exists()

    def test_complete_bootstrap_archives_and_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        bootstrap = tmp_path / "personal" / "WORKSPACE" / "BOOTSTRAP.md"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("bootstrap body", encoding="utf-8")

        assert AgentManager.complete_bootstrap() is True

        assert AgentManager.is_bootstrapped() is True
        assert not bootstrap.exists()
        archives = list((tmp_path / "personal" / "WORKSPACE" / ".archive" / "bootstrap").glob("BOOTSTRAP.completed.*.md"))
        assert archives
        assert archives[0].read_text(encoding="utf-8") == "bootstrap body"

    def test_complete_bootstrap_endpoint(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
        bootstrap = tmp_path / "personal" / "WORKSPACE" / "BOOTSTRAP.md"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("bootstrap body", encoding="utf-8")

        response = client.post("/api/agents/personal/bootstrap/complete")

        assert response.status_code == 200
        assert response.json()["bootstrapped"] is True
        assert not bootstrap.exists()


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated_at_newline(self):
        text = "line one\nline two\nline three"
        result = _truncate(text, 20)
        assert len(result) <= 20
