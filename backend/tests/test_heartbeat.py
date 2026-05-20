import asyncio
import os
import time

import pytest

from app.agents.heartbeat import HeartbeatEngine
from app.agents.manager import AgentManager


@pytest.fixture(autouse=True)
def isolate_memory_os(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.memory_os.DB_PATH", tmp_path / "memory_os.db")
    monkeypatch.setattr("app.agents.memory_os._memory_os", None)
    monkeypatch.setattr("app.agents.memory_os._sqlite_vec_available", lambda: False)


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


@pytest.mark.asyncio
async def test_heartbeat_writes_handoff_and_auto_memory_items(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")

    result = await HeartbeatEngine.on_session_end(
        [
            {"role": "user", "content": "请记住：Memory OS 应由 Agent 自动维护，用户只负责查看、纠错和删除。"},
            {"role": "assistant", "content": "我会把记忆、梦境和学习定位为后台自动能力。"},
        ],
        "auto-memory-test",
    )

    assert result["diary_written"] is True
    assert result["handoff_written"] is True
    assert result["memory_items_stored"] >= 3
    handoff = AgentManager._personal_dir() / "session_handoff.md"
    assert handoff.exists()
    assert "auto-memory-test" in handoff.read_text(encoding="utf-8")

    from app.agents.memory_os import get_memory_os

    memory_os = get_memory_os()
    assert memory_os.search("自动维护", memory_type="semantic")
    assert memory_os.search("Session handoff", memory_type="working")
    assert memory_os.search("自动能力", memory_type="episodic")


@pytest.mark.asyncio
async def test_heartbeat_skips_duplicate_session_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")
    messages = [
        {"role": "user", "content": "请记住：自动记忆维护应该在会话结束后运行。"},
        {"role": "assistant", "content": "我会在结束钩子里自动摘要并写入记忆。"},
    ]

    first = await HeartbeatEngine.on_session_end(messages, "dedupe-test")
    second = await HeartbeatEngine.on_session_end(messages, "dedupe-test")

    assert first["skipped_duplicate"] is False
    assert second["skipped_duplicate"] is True
    diary = AgentManager._memory_dir() / f"{time.strftime('%Y-%m-%d')}.md"
    assert diary.read_text(encoding="utf-8").count("Session Summary") == 1


@pytest.mark.asyncio
async def test_heartbeat_records_learning_and_feature_request_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")

    result = await HeartbeatEngine.on_session_end(
        [
            {"role": "assistant", "content": "记忆系统需要用户手动管理。"},
            {"role": "user", "content": "不对，正确的是记忆系统默认自动维护。你能不能在会话结束自动摘要？"},
        ],
        "learning-signal-test",
    )

    assert result["learnings_recorded"] == 1
    assert result["feature_requests_recorded"] == 1
    learnings_dir = AgentManager._personal_dir() / ".learnings"
    assert "记忆系统默认自动维护" in (learnings_dir / "LEARNINGS.md").read_text(encoding="utf-8")
    assert "会话结束自动摘要" in (learnings_dir / "FEATURE_REQUESTS.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_session_runtime_runs_heartbeat_after_personal_turn(monkeypatch):
    from app.agent import AgentSession
    from app.session_runtime import SessionRuntime

    called = {}
    heartbeat_started = asyncio.Event()
    heartbeat_release = asyncio.Event()

    async def fake_heartbeat(messages, session_id):
        called["session_id"] = session_id
        called["messages"] = messages
        heartbeat_started.set()
        await heartbeat_release.wait()
        return {"diary_written": True}

    monkeypatch.setattr("app.agents.heartbeat.HeartbeatEngine.on_session_end", fake_heartbeat)
    session = AgentSession("gpt-4o", session_id="runtime-heartbeat-test", agent_type="personal")
    session.messages = [{"role": "user", "content": "请记住：运行完成后自动维护记忆。"}]
    runtime = SessionRuntime(session.session_id)
    queue = runtime.subscribe()

    async def run_factory():
        yield {"type": "run_completed", "data": {"status": "completed"}}

    await runtime.start(session, run_factory)
    task = runtime._task
    assert task is not None
    seen = []
    for _ in range(2):
        event = await asyncio.wait_for(queue.get(), timeout=1)
        seen.append(event["type"])
        if event["type"] == "done":
            break
    await asyncio.wait_for(task, timeout=1)

    assert "done" in seen
    assert runtime.is_running is False
    assert runtime.accepts_task_guidance is False
    await asyncio.wait_for(heartbeat_started.wait(), timeout=1)
    assert called["session_id"] == "runtime-heartbeat-test"
    assert called["messages"] == session.messages
    heartbeat_release.set()
    await asyncio.sleep(0)


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
