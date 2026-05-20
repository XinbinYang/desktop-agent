import pytest

from app.agents.manager import AgentManager
from app.agents.memory_os import MemoryOS


@pytest.fixture
def memory_os(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)
    return MemoryOS(tmp_path / "memory_os.db")


def test_memory_os_search_patch_delete(memory_os):
    item = memory_os.upsert_item(
        content="User prefers pytest for backend verification.",
        memory_type="semantic",
        source="test",
        source_ref="test:1",
        tier="hot",
        confidence=0.9,
        created_by="test",
    )

    results = memory_os.search("pytest", limit=5)
    assert results
    assert results[0]["id"] == item["id"]
    assert results[0]["memory_type"] == "semantic"

    updated = memory_os.patch_item(item["id"], {"tier": "cold", "summary": "pytest preference"})
    assert updated is not None
    assert updated["tier"] == "cold"
    assert updated["summary"] == "pytest preference"

    assert memory_os.delete_item(item["id"]) is True
    assert memory_os.search("pytest") == []


def test_memory_os_rebuild_from_runtime_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")
    personal_dir = AgentManager._personal_dir()
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    (personal_dir / "MEMORY.md").write_text(
        "# MEMORY.md\n\n## Current\n\n- [HOT] User likes concise implementation notes.\n",
        encoding="utf-8",
    )
    (memory_dir / "2026-05-19.md").write_text(
        "# 2026-05-19\n\n## 10:00\n\nDiscussed Memory OS implementation and audit trails.",
        encoding="utf-8",
    )

    engine = MemoryOS(tmp_path / "memory_os.db")
    result = engine.rebuild_from_workspace()

    assert result["indexed"] >= 2
    assert engine.status()["total_items"] >= 2
    assert engine.search("audit trails", memory_type="episodic")
    assert engine.search("concise", memory_type="semantic")[0]["tier"] == "hot"


def test_memory_os_api_routes(tmp_path, monkeypatch, client):
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)

    from app.agents.memory_os import get_memory_os

    item = get_memory_os().upsert_item(
        content="Semantic recall should find hybrid memory records.",
        memory_type="semantic",
        source="api-test",
        source_ref="api-test:1",
        tier="warm",
    )

    status = client.get("/api/agents/personal/memory/status")
    assert status.status_code == 200
    assert status.json()["total_items"] == 1

    search = client.post("/api/agents/personal/memory/search", json={"query": "hybrid", "memory_type": "semantic"})
    assert search.status_code == 200
    assert search.json()["items"][0]["id"] == item["id"]

    patch = client.patch(
        f"/api/agents/personal/memory/items/{item['id']}",
        json={"tier": "cold"},
    )
    assert patch.status_code == 200
    assert patch.json()["item"]["tier"] == "cold"

    delete = client.delete(f"/api/agents/personal/memory/items/{item['id']}")
    assert delete.status_code == 200
    assert client.post("/api/agents/personal/memory/search", json={"query": "hybrid"}).json()["items"] == []


@pytest.mark.asyncio
async def test_memory_os_agent_tools(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)

    from app.tools import list_tool_names
    from app.tools.memory_tool import MemoryForgetTool, MemoryRememberTool, MemorySearchTool, MemoryUpdateTool

    tool_names = list_tool_names()
    assert "memory_remember" in tool_names
    assert "memory_update" in tool_names
    assert "memory_forget" in tool_names
    assert "memory_rebuild" in tool_names

    remember = await MemoryRememberTool().execute(
        content="User prefers concise implementation summaries.",
        memory_type="semantic",
        source_ref="user_explicit:test",
        confidence=0.92,
        tier="hot",
    )
    assert not remember.error
    item_id = remember.metadata["item"]["id"]

    search = await MemorySearchTool().execute("concise summaries")
    assert "user_explicit:test" in search.output
    assert item_id in search.output

    update = await MemoryUpdateTool().execute(item_id=item_id, tier="cold", summary="summary style preference")
    assert not update.error
    assert update.metadata["item"]["tier"] == "cold"

    forget = await MemoryForgetTool().execute(item_id=item_id)
    assert not forget.error
    search_after = await MemorySearchTool().execute("concise summaries")
    assert search_after.output == "No matching memories found."


@pytest.mark.asyncio
async def test_memory_remember_requires_high_confidence_for_identity(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)

    from app.tools.memory_tool import MemoryRememberTool

    result = await MemoryRememberTool().execute(
        content="The user has a new identity-level profile fact.",
        memory_type="identity",
        confidence=0.7,
    )

    assert "Identity memories require confidence" in result.error


@pytest.mark.asyncio
async def test_dream_records_memory_os_entries(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")

    from app.agents.dream import DreamEngine
    from app.agents.memory_os import get_memory_os

    personal_dir = AgentManager._personal_dir()
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(5):
        (memory_dir / f"2026-05-{idx + 1:02d}.md").write_text(
            "User repeatedly prefers memory audit trails and local-first storage.\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        DreamEngine,
        "_deep_sleep",
        classmethod(lambda cls, candidates: ([(candidates[0], 0.91)] if candidates else [], [])),
    )
    monkeypatch.setattr(DreamEngine, "_rem_async", classmethod(lambda cls, passed, candidates: _async_dict()))

    result = await DreamEngine.run()

    assert result["deep_sleep"]["passed"] >= 1
    assert get_memory_os().search("local-first", memory_type="semantic")
    assert (personal_dir / "MEMORY.md").exists()


async def _async_dict():
    return {"patterns": [], "suggestions": []}
