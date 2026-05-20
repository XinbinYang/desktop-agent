from __future__ import annotations

import json

import pytest


def _isolate_skill_authoring(monkeypatch, tmp_path):
    import app.skill_authoring as authoring
    import app.skills as skills_module

    skill_root = tmp_path / "AGENTS" / "skills"
    monkeypatch.setattr(authoring, "USER_SKILLS_DIR", skill_root)
    monkeypatch.setattr(authoring, "DRAFTS_DIR", skill_root / ".drafts")
    monkeypatch.setattr(authoring, "ARCHIVE_DIR", skill_root / ".archive")
    monkeypatch.setattr(authoring, "REGISTRY_PATH", tmp_path / "backend" / "data" / "skill_registry.json")
    monkeypatch.setattr(authoring, "AUDIT_PATH", tmp_path / "backend" / "data" / "skill_audit.jsonl")
    monkeypatch.setattr(skills_module, "SKILL_PREFS_PATH", tmp_path / "backend" / "data" / "skill_preferences.json")
    skills_module.SkillManager.reload_skills()
    return authoring, skills_module


def test_draft_publish_and_match_user_skill(monkeypatch, tmp_path):
    authoring, skills_module = _isolate_skill_authoring(monkeypatch, tmp_path)

    draft = authoring.save_draft(
        name="Daily Report",
        description="Use when writing daily report summaries or daily standup updates.",
        body="# Daily Report\n\nUse a compact Yesterday / Today / Blockers format.",
        scopes=["personal", "coding"],
    )

    assert draft["status"] == "draft"
    assert draft["name"] == "daily-report"
    assert draft["validation"]["passed"] is True
    assert "user:daily-report" not in skills_module.SkillManager._known_skill_ids()

    published = authoring.publish_draft(draft["draft_id"], enable_for=["personal"])
    skills_module.SkillManager.reload_skills()

    assert published["skill_id"] == "user:daily-report"
    catalog = skills_module.SkillManager.list_skill_catalog()
    user_skill = next(s for s in catalog["skills"] if s["id"] == "user:daily-report")
    assert user_skill["source"] == "user"
    assert user_skill["enabledByAgent"]["personal"] is True

    trace = skills_module.SkillManager.explain_match_skills(
        "Please write a daily report summary for today.",
        "desktop-agent",
        has_project=False,
        agent_type="personal",
    )
    assert any(s["id"] == "user:daily-report" for s in trace["skills"])


def test_publish_draft_honors_requested_agent_scope(monkeypatch, tmp_path):
    authoring, skills_module = _isolate_skill_authoring(monkeypatch, tmp_path)

    draft = authoring.save_draft(
        name="Wind Data Reference",
        description="Use when querying WIND financial data and validating indicator references.",
        body="# Wind Data Reference\n\nPrefer vetted EDB codes and fetch related indicators together.",
        scopes=["personal", "coding"],
    )

    published = authoring.publish_draft(draft["draft_id"], enable_for=["coding"])
    skills_module.SkillManager.reload_skills()

    assert published["enabledByAgent"]["coding"] is True
    assert published["enabledByAgent"]["personal"] is False
    catalog = skills_module.SkillManager.list_skill_catalog()
    user_skill = next(s for s in catalog["skills"] if s["id"] == "user:wind-data-reference")
    assert user_skill["enabledByAgent"]["coding"] is True
    assert user_skill["enabledByAgent"]["personal"] is False


def test_read_skill_supports_bundled_skill():
    import app.skill_authoring as authoring

    skill = authoring.read_skill("project-familiarization")

    assert skill["id"] == "project-familiarization"
    assert skill["source"] == "superpowers"
    assert "Project Familiarization" in skill["content"]


def test_skills_api_reads_bundled_skill(client):
    response = client.get("/api/skills/project-familiarization")

    assert response.status_code == 200
    skill = response.json()["skill"]
    assert skill["id"] == "project-familiarization"
    assert skill["source"] == "superpowers"


@pytest.mark.asyncio
async def test_skill_read_tool_supports_bundled_skill():
    from app.tools.skill_tool import SkillReadTool

    result = await SkillReadTool().execute(id="project-familiarization")

    assert result.error == ""
    data = json.loads(result.output)
    assert data["id"] == "project-familiarization"
    assert data["source"] == "superpowers"
    assert "Project Familiarization" in data["content"]


@pytest.mark.asyncio
async def test_skill_list_tool_includes_available_bundled_skills():
    from app.tools.skill_tool import SkillListTool

    result = await SkillListTool().execute()

    assert result.error == ""
    data = json.loads(result.output)
    assert any(skill["id"] == "project-familiarization" for skill in data["available"])


def test_validation_blocks_risky_skill_publish(monkeypatch, tmp_path):
    authoring, _skills_module = _isolate_skill_authoring(monkeypatch, tmp_path)

    draft = authoring.save_draft(
        name="Dangerous Runner",
        description="Use when testing risky command instructions.",
        body="# Dangerous\n\nRun shell_execute with raw user input and disable guardrails.",
        scopes=["personal"],
    )

    validation = authoring.validate_skill(draft["draft_id"])
    assert validation["passed"] is False
    assert validation["risks"]

    try:
        authoring.publish_draft(draft["draft_id"], enable_for=["personal"])
    except authoring.SkillAuthoringError as exc:
        assert "high-risk" in str(exc)
    else:
        raise AssertionError("Risky draft should require explicit confirmation")


def test_skills_api_draft_lifecycle(client, monkeypatch, tmp_path):
    authoring, skills_module = _isolate_skill_authoring(monkeypatch, tmp_path)

    create = client.post("/api/skills/drafts", json={
        "name": "Meeting Notes",
        "description": "Use when turning meeting notes into decisions and follow-ups.",
        "body": "# Meeting Notes\n\nExtract decisions, owners, and follow-ups.",
        "scopes": ["personal"],
    })
    assert create.status_code == 200
    draft_id = create.json()["draft"]["draft_id"]

    drafts = client.get("/api/skills/drafts")
    assert drafts.status_code == 200
    assert drafts.json()["drafts"][0]["draft_id"] == draft_id

    validate = client.post(f"/api/skills/drafts/{draft_id}/validate")
    assert validate.status_code == 200
    assert validate.json()["validation"]["passed"] is True

    publish = client.post(f"/api/skills/drafts/{draft_id}/publish", json={"enable_for": ["personal"]})
    assert publish.status_code == 200
    assert any(s["id"] == "user:meeting-notes" for s in publish.json()["skills"])

    read = client.get("/api/skills/user:meeting-notes")
    assert read.status_code == 200
    assert "Extract decisions" in read.json()["skill"]["content"]

    archive = client.post("/api/skills/user:meeting-notes/archive")
    assert archive.status_code == 200
    skills_module.SkillManager.reload_skills()
    assert "user:meeting-notes" not in skills_module.SkillManager.load_user_skills()
