import os
import time

import pytest

from app.agents.heartbeat import HeartbeatEngine
from app.agents.manager import AgentManager


@pytest.mark.asyncio
async def test_heartbeat_runs_dream_when_threshold_met(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)
    for idx in range(HeartbeatEngine.DREAM_SESSION_COUNT_THRESHOLD):
        (memory_dir / f"2026-05-{idx + 1:02d}.md").write_text(
            "# diary\n\nrepeated preference and project context\n",
            encoding="utf-8",
        )

    called = {}

    async def fake_dream_run():
        called["ran"] = True
        return {"deep_sleep": {"passed": 1}}

    monkeypatch.setattr("app.agents.dream.DreamEngine.run", fake_dream_run)

    result = await HeartbeatEngine.on_session_end(
        [{"role": "user", "content": "Please remember this session summary."}],
        "heartbeat-test",
    )

    assert called["ran"] is True
    assert result["dream_triggered"] is True
    assert result["dream_result"] == {"deep_sleep": {"passed": 1}}
    assert result["dream_error"] == ""


def test_should_trigger_dream_counts_only_diaries_after_last_dream(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path)
    personal_dir = AgentManager._personal_dir()
    memory_dir = AgentManager._memory_dir()
    memory_dir.mkdir(parents=True)
    diary = memory_dir / "2026-05-01.md"
    diary.write_text("x" * (HeartbeatEngine.DREAM_DIARY_SIZE_THRESHOLD + 1), encoding="utf-8")
    dreams = personal_dir / "DREAMS.md"
    dreams.write_text("latest dream", encoding="utf-8")

    old_time = time.time() - 120
    new_time = time.time()
    os.utime(diary, (old_time, old_time))
    os.utime(dreams, (new_time, new_time))

    assert HeartbeatEngine._should_trigger_dream() is False
