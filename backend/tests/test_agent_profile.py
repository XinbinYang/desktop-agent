import json

from app.agents.manager import AgentManager


def test_profile_json_is_primary_source(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    profile_path = AgentManager._personal_dir() / "profile.json"
    profile_path.write_text(
        json.dumps({
            "agent_type": "personal",
            "display_name": "Mirror Blade",
            "type_label": "Personal Agent",
            "avatar_emoji": "*",
            "subtitle": "Macro companion",
            "updated_at": "2026-05-20T10:00:00",
        }),
        encoding="utf-8",
    )
    (AgentManager._personal_dir() / "IDENTITY.md").write_text("- **名字：** Other\n", encoding="utf-8")

    profile = AgentManager.get_agent_profile("personal")

    assert profile["display_name"] == "Mirror Blade"
    assert profile["avatar_emoji"] == "*"
    assert profile["source"] == "profile.json"


def test_profile_falls_back_to_identity_frontmatter(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    (AgentManager._personal_dir() / "IDENTITY.md").write_text(
        "---\nname: Front Name\ndescription: Front subtitle\nemoji: F\n---\n\n# Identity\n",
        encoding="utf-8",
    )

    profile = AgentManager.get_agent_profile("personal")

    assert profile["display_name"] == "Front Name"
    assert profile["subtitle"] == "Front subtitle"
    assert profile["avatar_emoji"] == "F"
    assert profile["source"] == "IDENTITY.md"


def test_profile_falls_back_to_identity_chinese_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    (AgentManager._personal_dir() / "IDENTITY.md").write_text(
        "# IDENTITY.md\n\n- **名字：** 镜与刃\n- **角色：** 宏观作手的AI化身\n- **Emoji：** ♟\n",
        encoding="utf-8",
    )

    profile = AgentManager.get_agent_profile("personal")

    assert profile["display_name"] == "镜与刃"
    assert profile["subtitle"] == "宏观作手的AI化身"
    assert profile["avatar_emoji"] == "♟"


def test_profile_falls_back_to_personal_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)

    profile = AgentManager.get_agent_profile("personal")

    assert profile["display_name"] == "Personal Agent"
    assert profile["type_label"] == "Personal Agent"
    assert profile["source"] == "default"


def test_patch_profile_roundtrip(client, tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    (AgentManager._personal_dir() / "IDENTITY.md").write_text("- **名字：** Old\n", encoding="utf-8")

    response = client.patch(
        "/api/agents/personal/profile",
        json={"display_name": "镜与刃", "avatar_emoji": "M", "subtitle": "Sharp mirror"},
    )
    assert response.status_code == 200
    assert response.json()["profile"]["display_name"] == "镜与刃"

    response = client.get("/api/agents/personal/profile")
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["display_name"] == "镜与刃"
    assert profile["avatar_emoji"] == "M"
    assert profile["subtitle"] == "Sharp mirror"
    assert "镜与刃" in (AgentManager._personal_dir() / "IDENTITY.md").read_text(encoding="utf-8")
