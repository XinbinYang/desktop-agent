import pytest
from app.roles import RoleManager, Role


class TestRoleManager:
    def test_list_roles_returns_builtin_roles(self):
        """RoleManager should load all builtin roles from markdown files."""
        roles = RoleManager.list_roles()
        assert len(roles) >= 4
        ids = [r["id"] for r in roles]
        assert "desktop-agent" in ids
        assert "general-assistant" in ids
        assert "quant-analyst" in ids
        assert "code-expert" in ids

    def test_get_role_valid(self):
        """Getting a valid role returns a Role object."""
        role = RoleManager.get_role("desktop-agent")
        assert role is not None
        assert role.id == "desktop-agent"
        assert role.name == "桌面助手"
        assert role.is_builtin is True
        assert "{{tools_desc}}" in role.prompt_template

    def test_get_role_invalid_returns_none(self):
        """Getting an invalid role returns None."""
        role = RoleManager.get_role("nonexistent-role")
        assert role is None

    def test_render_prompt_replaces_placeholder(self):
        """render_prompt should replace {{tools_desc}} with the provided tools description."""
        prompt = RoleManager.render_prompt("general-assistant", "- tool1: desc1\n- tool2: desc2")
        assert "{{tools_desc}}" not in prompt
        assert "tool1: desc1" in prompt
        assert "tool2: desc2" in prompt

    def test_render_prompt_invalid_role_fallback(self):
        """render_prompt with invalid role falls back to desktop-agent."""
        prompt = RoleManager.render_prompt("nonexistent", "tools")
        assert "tools" in prompt

    def test_reload_clears_cache(self):
        """reload should clear the internal cache and reload roles."""
        # Load once to populate cache
        roles1 = RoleManager.list_roles()
        RoleManager.reload()
        roles2 = RoleManager.list_roles()
        assert len(roles1) == len(roles2)

    def test_role_parse_frontmatter(self):
        """Role markdown files should have correct name and description from frontmatter."""
        role = RoleManager.get_role("code-expert")
        assert role is not None
        assert role.name == "代码专家"
        assert "全栈代码专家" in role.description

    def test_code_expert_contains_workflow_sections(self):
        """code-expert prompt should contain complexity tiers."""
        role = RoleManager.get_role("code-expert")
        assert role is not None
        assert "Trivial" in role.prompt_template
        assert "Complex" in role.prompt_template
        assert "verification-before-completion" in role.prompt_template
        assert "brainstorming" in role.prompt_template
        assert "writing-plans" in role.prompt_template

    def test_code_expert_contains_tool_best_practices(self):
        """code-expert prompt should contain tool usage guidance."""
        role = RoleManager.get_role("code-expert")
        assert role is not None
        assert "file_read" in role.prompt_template
        assert "file_search" in role.prompt_template
        assert "dispatch_worker" in role.prompt_template

    def test_code_expert_contains_safety_guardrails(self):
        """code-expert prompt should contain irreversible operation guardrails."""
        role = RoleManager.get_role("code-expert")
        assert role is not None
        assert "git push --force" in role.prompt_template
        assert "git reset --hard" in role.prompt_template
        assert "rm -rf" in role.prompt_template
