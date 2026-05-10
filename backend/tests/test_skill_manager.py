import pytest
from app.skills import SkillManager


@pytest.fixture(autouse=True)
def reload_skills():
    """Reload skills before each test"""
    SkillManager.reload_skills()
    yield


class TestSkillManager:
    def test_load_skills(self):
        """Skills are loaded from backend/prompts/skills/"""
        skills = SkillManager.load_skills()
        assert len(skills) > 0
        # Core Superpowers skills should exist
        core_skills = [
            "using-superpowers", "brainstorming", "writing-plans",
            "test-driven-development", "using-git-worktrees"
        ]
        for name in core_skills:
            assert name in skills, f"Missing skill: {name}"

    def test_list_skills(self):
        """list_skills returns brief info for all skills"""
        skills = SkillManager.list_skills()
        assert len(skills) > 0
        for s in skills:
            assert "name" in s
            assert "description" in s

    def test_get_skill(self):
        """get_skill returns full skill content with frontmatter"""
        content = SkillManager.get_skill("using-superpowers")
        assert content is not None
        assert "using-superpowers" in content
        assert "---" in content  # YAML frontmatter

    def test_get_skill_body(self):
        """get_skill_body returns content without frontmatter"""
        body = SkillManager.get_skill_body("using-superpowers")
        assert body is not None
        assert len(body) > 0

    def test_get_unknown_skill(self):
        """get_skill returns None for unknown skill"""
        assert SkillManager.get_skill("nonexistent-skill-12345") is None

    def test_match_skills_code_expert(self):
        """Programming messages match relevant skills for code-expert"""
        matched = SkillManager.match_skills("帮我实现一个登录功能", "code-expert", True)
        assert "using-superpowers" in matched
        assert "brainstorming" in matched

    def test_match_skills_debug(self):
        """Debug messages match debugging skills"""
        matched = SkillManager.match_skills("这里有个 Bug 需要修复", "code-expert", True)
        assert "systematic-debugging" in matched
        assert "test-driven-development" in matched

    def test_match_skills_refactor(self):
        """Refactor messages match TDD skill"""
        matched = SkillManager.match_skills("重构这段代码", "code-expert", True)
        assert "test-driven-development" in matched

    def test_match_skills_non_code_role(self):
        """Non-code-expert role doesn't match code skills"""
        matched = SkillManager.match_skills("帮我实现一个功能", "general-assistant", True)
        # Should not include code-specific skills
        assert "brainstorming" not in matched

    def test_match_skills_no_project(self):
        """Without project, basic matching still works but using-superpowers is not auto-added"""
        matched = SkillManager.match_skills("写个 Python 脚本", "code-expert", False)
        # "写个" matches the first rule which includes using-superpowers
        assert "brainstorming" in matched
        # The has_project-only auto-add is not triggered, but rule-based match is

    def test_match_skills_adds_writing_plans_for_develop(self):
        """Development tasks also match writing-plans skill."""
        matched = SkillManager.match_skills("开发一个新功能", "code-expert", True)
        assert "writing-plans" in matched

    def test_match_skills_verification_for_refactor(self):
        """Refactor tasks include verification-before-completion."""
        matched = SkillManager.match_skills("重构这段代码", "code-expert", True)
        assert "test-driven-development" in matched
        assert "verification-before-completion" in matched

    def test_match_skills_finishing_branch(self):
        """Branch finishing tasks match finishing-a-development-branch."""
        matched = SkillManager.match_skills("完成这个功能，合并到主干", "code-expert", True)
        assert "finishing-a-development-branch" in matched
        assert "verification-before-completion" in matched

    def test_match_skills_executing_plans(self):
        """Plan execution tasks match executing-plans."""
        matched = SkillManager.match_skills("按计划执行这个实现", "code-expert", True)
        assert "executing-plans" in matched
        assert "subagent-driven-development" in matched

    def test_match_skills_review_feedback(self):
        """Review feedback tasks match receiving-code-review."""
        matched = SkillManager.match_skills("根据代码审查反馈修改", "code-expert", True)
        assert "receiving-code-review" in matched

    def test_match_skills_always_verification_for_code_expert(self):
        """code-expert always gets verification-before-completion even for non-obvious matches."""
        matched = SkillManager.match_skills("hello world", "code-expert", True)
        # No specific rule should match, but verification is always injected
        assert "using-superpowers" in matched
        assert "verification-before-completion" in matched

    def test_match_skills_non_code_expert_no_verification_auto(self):
        """Non-code-expert roles don't get auto verification injection."""
        matched = SkillManager.match_skills("重构这段代码", "general-assistant", True)
        assert "verification-before-completion" not in matched

    def test_build_skill_prompt(self):
        """build_skill_prompt merges multiple skills"""
        prompt = SkillManager.build_skill_prompt(["using-superpowers", "brainstorming"])
        assert "using-superpowers" in prompt
        assert "brainstorming" in prompt

    def test_build_skill_prompt_empty(self):
        """build_skill_prompt with empty list returns empty string"""
        prompt = SkillManager.build_skill_prompt([])
        assert prompt == ""
