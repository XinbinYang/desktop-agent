from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.manager import AgentManager


def _isolate_specialists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import app.agents.specialists as specialists

    agents_root = tmp_path / "AGENTS"
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", agents_root)
    monkeypatch.setattr(specialists, "REGISTRY_PATH", tmp_path / "data" / "specialist_agent_registry.json")
    monkeypatch.setattr(specialists, "AUDIT_PATH", tmp_path / "data" / "specialist_agent_audit.jsonl")
    specialists.SpecialistRegistry.reload()
    return specialists


def _publish_market_specialist(specialists, **overrides):
    draft = specialists.save_draft(
        slug=overrides.get("slug", "stock-long-short"),
        display_name=overrides.get("display_name", "Stock Long Short"),
        description=overrides.get("description", "Use when producing disciplined stock long/short analysis."),
        instructions=overrides.get("instructions", "Always answer with the six-part long/short checklist."),
        trigger_examples=overrides.get("trigger_examples", ["股票多空怎么看", "analyze this stock long short"]),
        routing_keywords=overrides.get("routing_keywords", ["股票多空", "long short"]),
        auto_delegate=overrides.get("auto_delegate", "suggest"),
        base_kind=overrides.get("base_kind", "advisory"),
        allowed_tools=overrides.get("allowed_tools", ["web_search", "web_fetch", "knowledge_search", "knowledge_list"]),
        skill_ids=overrides.get("skill_ids", []),
        model_id=overrides.get("model_id", ""),
        thinking_intensity=overrides.get("thinking_intensity", "medium"),
    )
    return specialists.publish_draft(draft["draft_id"], allow_risky=True)


def test_specialist_draft_publish_and_agent_catalog(monkeypatch, tmp_path):
    specialists = _isolate_specialists(monkeypatch, tmp_path)

    published = _publish_market_specialist(specialists)

    assert published["agent_type"] == "specialist:stock-long-short"
    assert published["status"] == "published"
    assert (tmp_path / "AGENTS" / "specialists" / "stock-long-short" / "specialist.json").exists()
    agents = AgentManager.list_agents()
    specialist = next(agent for agent in agents if agent["type"] == "specialist:stock-long-short")
    assert specialist["name"] == "Stock Long Short"
    assert specialist["profile"]["display_name"] == "Stock Long Short"


def test_specialist_prompt_injects_specialist_and_shared_context_only(monkeypatch, tmp_path):
    specialists = _isolate_specialists(monkeypatch, tmp_path)
    _publish_market_specialist(
        specialists,
        slug="market-discipline",
        display_name="Market Discipline",
        instructions="SPECIALIST_SENTINEL: enforce numeric entry/stop/target discipline.",
    )
    AgentManager.save_workspace_file("_shared", "user_preferences.md", "SHARED_PREF_SENTINEL")
    AgentManager.save_workspace_file("personal", "USER.md", "PRIVATE_USER_SENTINEL")
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "2026-05-26.md").write_text("PRIVATE_DIARY_SENTINEL", encoding="utf-8")

    prompt = AgentManager.render_prompt("specialist:market-discipline", "TOOLS_DESC")

    assert "SPECIALIST_SENTINEL" in prompt
    assert "SHARED_PREF_SENTINEL" in prompt
    assert "TOOLS_DESC" in prompt
    assert "PRIVATE_USER_SENTINEL" not in prompt
    assert "PRIVATE_DIARY_SENTINEL" not in prompt


def test_personal_prompt_explains_skill_vs_specialist_boundary(monkeypatch, tmp_path):
    _isolate_specialists(monkeypatch, tmp_path)

    prompt = AgentManager.render_prompt("personal", "TOOLS_DESC")

    assert "specialist_agent_draft_save" in prompt
    assert "delegate_to_specialist_agent" in prompt
    assert "single reusable workflow" in prompt
    assert "independent identity" in prompt


def test_unknown_agent_type_does_not_render_as_personal(monkeypatch, tmp_path):
    _isolate_specialists(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="Unknown agent_type"):
        AgentManager.render_prompt("specialist:not-published", "TOOLS_DESC")

    with pytest.raises(ValueError, match="Unknown agent_type"):
        AgentManager.render_prompt("not-a-real-agent", "TOOLS_DESC")


def test_specialist_tool_schema_respects_allowed_tools(monkeypatch, tmp_path):
    specialists = _isolate_specialists(monkeypatch, tmp_path)
    _publish_market_specialist(
        specialists,
        slug="read-only-market",
        allowed_tools=["web_search", "knowledge_search"],
    )
    from app.tools import get_tool_schemas, list_tool_names

    names = {schema["function"]["name"] for schema in get_tool_schemas(agent_type="specialist:read-only-market")}

    assert names == {"web_search", "knowledge_search"}
    assert list_tool_names(agent_type="specialist:read-only-market") == ["web_search", "knowledge_search"]


def test_unknown_specialist_agent_type_gets_no_tools(monkeypatch, tmp_path):
    _isolate_specialists(monkeypatch, tmp_path)
    from app.tools import get_tool_schemas, list_tool_names

    assert get_tool_schemas(agent_type="specialist:not-published") == []
    assert list_tool_names(agent_type="specialist:not-published") == []


def test_personal_agent_can_author_and_delegate_specialists():
    from app.tools import get_tool_schemas

    names = {schema["function"]["name"] for schema in get_tool_schemas(agent_type="personal")}

    assert {
        "specialist_agent_draft_save",
        "specialist_agent_validate",
        "specialist_agent_publish",
        "specialist_agent_list",
        "specialist_agent_read",
        "specialist_agent_archive",
        "delegate_to_specialist_agent",
    } <= names


def test_specialist_draft_rejects_unknown_tool(monkeypatch, tmp_path):
    specialists = _isolate_specialists(monkeypatch, tmp_path)

    with pytest.raises(specialists.SpecialistAuthoringError, match="Unknown tool"):
        specialists.save_draft(
            slug="bad-tools",
            display_name="Bad Tools",
            description="Reject specialists that request tools outside the registry.",
            instructions="Use only explicitly authorized tools and report blockers.",
            allowed_tools=["web_search", "definitely_not_a_tool"],
        )


def test_resolve_specialist_session(monkeypatch, tmp_path, isolate_projects):
    specialists = _isolate_specialists(monkeypatch, tmp_path)
    _publish_market_specialist(specialists, slug="macro-router", display_name="Macro Router")
    from app.agent import SESSIONS_DIR, resolve_agent_session

    monkeypatch.setattr("app.agent.SESSIONS_DIR", tmp_path / "sessions")

    resolved = resolve_agent_session("specialist:macro-router", "last_or_create")

    assert resolved["agent_type"] == "specialist:macro-router"
    assert resolved["role_id"] == "desktop-agent"
    assert resolved["is_primary"] is False
    saved = json.loads((tmp_path / "sessions" / f"{resolved['session_id']}.json").read_text(encoding="utf-8"))
    assert saved["agent_type"] == "specialist:macro-router"
    assert not SESSIONS_DIR.joinpath("__unused__").exists()


def test_specialist_rest_lifecycle(client, monkeypatch, tmp_path):
    specialists = _isolate_specialists(monkeypatch, tmp_path)

    create = client.post("/api/agents/specialists/drafts", json={
        "slug": "meeting-decisions",
        "display_name": "Meeting Decisions",
        "description": "Use when turning meeting notes into decisions and follow-ups.",
        "instructions": "Extract decisions, owners, dates, and open questions.",
        "trigger_examples": ["summarize meeting decisions"],
        "routing_keywords": ["meeting decisions"],
        "auto_delegate": "suggest",
        "base_kind": "advisory",
        "allowed_tools": ["knowledge_search"],
        "skill_ids": [],
        "model_id": "",
        "thinking_intensity": "medium",
    })
    assert create.status_code == 200
    draft_id = create.json()["draft"]["draft_id"]

    validate = client.post(f"/api/agents/specialists/drafts/{draft_id}/validate")
    assert validate.status_code == 200
    assert validate.json()["validation"]["passed"] is True

    publish = client.post(f"/api/agents/specialists/drafts/{draft_id}/publish", json={"allow_risky": False})
    assert publish.status_code == 200
    assert publish.json()["specialist"]["agent_type"] == "specialist:meeting-decisions"

    listing = client.get("/api/agents/specialists")
    assert listing.status_code == 200
    assert any(item["slug"] == "meeting-decisions" for item in listing.json()["specialists"])

    archive = client.post("/api/agents/specialists/meeting-decisions/archive")
    assert archive.status_code == 200
    assert specialists.SpecialistRegistry.get("meeting-decisions") is None
