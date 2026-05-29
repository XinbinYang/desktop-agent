import pytest

from app.agents.dream import DreamEngine
from app.agents.manager import AgentManager


@pytest.mark.asyncio
async def test_dream_run_handles_empty_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)

    result = await DreamEngine.run()

    assert result["light_sleep"]["candidates_found"] == 0
    assert result["deep_sleep"]["passed"] == 0
    assert result["rem"] == {"patterns": [], "suggestions": []}


@pytest.mark.asyncio
async def test_dream_skips_second_incremental_run_without_new_diary(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-05-20.md").write_text(
        "请记住：用户偏好记忆系统本地优先并保留审计轨迹。\n" * 4,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        DreamEngine,
        "_deep_sleep",
        classmethod(lambda cls, candidates: ([(candidates[0], 0.91)] if candidates else [], [])),
    )
    monkeypatch.setattr(DreamEngine, "_rem_async", classmethod(lambda cls, passed, candidates: _async_dict()))

    first = await DreamEngine.run()
    second = await DreamEngine.run()

    assert first["light_sleep"]["candidates_found"] >= 1
    assert second["skipped"] is True
    assert second["light_sleep"]["candidates_found"] == 0


@pytest.mark.asyncio
async def test_force_dream_is_idempotent_for_memory_and_forgotten_log(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-05-20.md").write_text(
        "请记住：用户偏好 Memory OS 幂等写入和本地审计。\n"
        "请记住：这条失败候选也不要重复写 forgotten log。\n",
        encoding="utf-8",
    )

    def fake_deep_sleep(cls, candidates):
        return ([(candidates[0], 0.92)], [(candidates[-1], "score 0.1 < 0.8")])

    monkeypatch.setattr(DreamEngine, "_deep_sleep", classmethod(fake_deep_sleep))
    monkeypatch.setattr(DreamEngine, "_rem_async", classmethod(lambda cls, passed, candidates: _async_dict()))

    await DreamEngine.run(force=True)
    await DreamEngine.run(force=True)

    memory_text = (AgentManager._personal_dir() / "MEMORY.md").read_text(encoding="utf-8")
    forgotten_text = (AgentManager._personal_dir() / "forgotten.log").read_text(encoding="utf-8")
    assert memory_text.count("Memory OS 幂等写入") == 1
    assert forgotten_text.count("失败候选") == 1


def test_light_sleep_filters_noisy_transcript_and_tool_table(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-05-20.md").write_text(
        "\n".join([
            "| tool | description |",
            "- Assistant: 完整的工具清单如下，包含 web_search 和 file_read。",
            "- Assistant: 你好，我可以帮你处理任务。",
            "- User: 请记住：用户明确偏好记忆修复先备份再软删除。",
        ]),
        encoding="utf-8",
    )

    candidates = DreamEngine._light_sleep(force=True)

    assert any("先备份再软删除" in item for item in candidates)
    assert all("完整的工具清单" not in item for item in candidates)
    assert all(not item.startswith("| tool") for item in candidates)


async def _async_dict():
    return {"patterns": [], "suggestions": []}
