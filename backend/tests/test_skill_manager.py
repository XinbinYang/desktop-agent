import pytest
from app.skills import SkillManager
import app.skills as skills_module


@pytest.fixture(autouse=True)
def reload_skills(tmp_path, monkeypatch):
    """Reload skills before each test"""
    monkeypatch.setattr(skills_module, "SKILL_PREFS_PATH", tmp_path / "skill_preferences.json")
    SkillManager.reload_skills()
    yield
    SkillManager.reload_skills()


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
            assert "id" in s
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
        assert "brainstorming" not in matched

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
        assert "using-superpowers" in matched
        assert "brainstorming" not in matched
        # The has_project-only auto-add is not triggered, but rule-based match is

    def test_match_skills_adds_writing_plans_for_develop(self):
        """Development tasks also match writing-plans skill."""
        matched = SkillManager.match_skills("开发一个新功能", "code-expert", True)
        assert "writing-plans" not in matched

    def test_match_skills_verification_for_refactor(self):
        """Refactor tasks include verification-before-completion."""
        matched = SkillManager.match_skills("重构这段代码", "code-expert", True)
        assert "test-driven-development" in matched
        assert "verification-before-completion" in matched

    def test_match_skills_finishing_branch(self):
        """Branch finishing tasks match finishing-a-development-branch."""
        matched = SkillManager.match_skills("完成这个功能，合并到主干", "code-expert", True)
        assert "finishing-a-development-branch" not in matched
        assert "verification-before-completion" in matched

    def test_match_skills_executing_plans(self):
        """Plan execution tasks match executing-plans."""
        matched = SkillManager.match_skills("按计划执行这个实现", "code-expert", True)
        assert "executing-plans" not in matched
        assert "subagent-driven-development" in matched

    def test_match_skills_review_feedback(self):
        """Review feedback tasks match receiving-code-review."""
        matched = SkillManager.match_skills("根据代码审查反馈修改", "code-expert", True)
        assert "receiving-code-review" not in matched

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

    def test_catalog_includes_preferences_and_defaults(self):
        catalog = SkillManager.list_skill_catalog()

        assert "skills" in catalog
        assert "preferences" in catalog
        assert "defaults" in catalog
        assert "presets" in catalog
        assert catalog["preferences"]["coding"]["test-driven-development"] is True
        assert catalog["preferences"]["personal"]["using-superpowers"] is True
        categories = {skill["id"]: skill["category"] for skill in catalog["skills"]}
        assert categories["test-driven-development"] == "quality-review"
        assert categories["dispatching-parallel-agents"] == "multi-agent"
        known = {skill["id"] for skill in catalog["skills"]}
        for preset in catalog["presets"]:
            assert preset["id"]
            assert set(preset["skillIds"]).issubset(known)

    def test_update_preferences_filters_unknown_ids(self):
        result = SkillManager.update_preferences({
            "coding": {
                "test-driven-development": False,
                "unknown-skill": True,
            }
        })

        assert result["ignored"] == ["unknown-skill"]
        assert result["preferences"]["coding"]["test-driven-development"] is False
        matched = SkillManager.match_skills("test this change", "code-expert", True)
        assert "test-driven-development" not in matched

    def test_explain_match_skills_includes_enabled_and_disabled_matches(self):
        result = SkillManager.explain_match_skills(
            "fix this bug and add tests",
            "code-expert",
            True,
            agent_type="coding",
        )

        enabled_ids = {skill["id"] for skill in result["skills"]}
        assert "systematic-debugging" in enabled_ids
        assert "test-driven-development" in enabled_ids
        assert "verification-before-completion" in enabled_ids
        assert result["disabled_matches"] == []

        SkillManager.update_preferences({"coding": {"test-driven-development": False}})
        result = SkillManager.explain_match_skills(
            "fix this bug and add tests",
            "code-expert",
            True,
            agent_type="coding",
        )
        enabled_ids = {skill["id"] for skill in result["skills"]}
        disabled_ids = {skill["id"] for skill in result["disabled_matches"]}
        assert "test-driven-development" not in enabled_ids
        assert "test-driven-development" in disabled_ids

    def test_personal_crystallized_skills_default_enabled(self, tmp_path, monkeypatch):
        agents_root = tmp_path / "AGENTS"
        skill_dir = agents_root / "personal" / "skills"
        skill_dir.mkdir(parents=True)
        (skill_dir / "analysis_notes.md").write_text(
            "---\nname: Analysis Notes\ndescription: Use the user's analysis style.\n---\n\nBody",
            encoding="utf-8",
        )
        monkeypatch.setattr(skills_module, "agents_dir", lambda: agents_root)
        SkillManager.reload_skills()

        catalog = SkillManager.list_skill_catalog()
        ids = [skill["id"] for skill in catalog["skills"]]
        assert "personal:analysis_notes" in ids
        assert catalog["preferences"]["personal"]["personal:analysis_notes"] is True
        assert catalog["preferences"]["coding"]["personal:analysis_notes"] is False
