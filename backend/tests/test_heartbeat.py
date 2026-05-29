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
    HeartbeatEngine._write_heartbeat_state({"sessions_since_last_dream": HeartbeatEngine.DREAM_SESSION_COUNT_THRESHOLD - 1})

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
    assert diary.read_text(encoding="utf-8").count("Session Delta") == 1


@pytest.mark.asyncio
async def test_heartbeat_duplicate_completion_and_disconnect_write_once(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")
    monkeypatch.setattr(HeartbeatEngine, "_should_trigger_dream", classmethod(lambda cls, **kwargs: False))
    messages = [
        {"role": "user", "content": "请记住：重复 heartbeat 不应该重复写入同一轮记忆。"},
        {"role": "assistant", "content": "我会用 session signature 去重。"},
    ]

    first = await HeartbeatEngine.on_session_end(messages, "double-fire-test")
    second = await HeartbeatEngine.on_session_end(messages, "double-fire-test")

    assert first["diary_written"] is True
    assert second["skipped_duplicate"] is True
    from app.agents.memory_os import get_memory_os

    memory_os = get_memory_os()
    assert len(memory_os.search("session signature", memory_type="working")) == 1
    diary = AgentManager._memory_dir() / f"{time.strftime('%Y-%m-%d')}.md"
    assert diary.read_text(encoding="utf-8").count("Session Delta") == 1


@pytest.mark.asyncio
async def test_heartbeat_writes_only_new_turn_deltas(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")
    monkeypatch.setattr(HeartbeatEngine, "_should_trigger_dream", classmethod(lambda cls, **kwargs: False))

    messages = []
    for idx in range(20):
        messages.extend([
            {
                "role": "user",
                "content": f"è¯·è®°ä½ï¼šç¬¬ {idx} è½® delta è®°å¿†åªå†™æ–°å†…å®¹ã€‚",
                "message_id": f"user-{idx}",
                "turn_id": f"turn-{idx}",
                "context_epoch": 0,
            },
            {
                "role": "assistant",
                "content": f"æˆ‘ä¼šåªè®°å½•ç¬¬ {idx} è½®æ–°å¢žéƒ¨åˆ†ã€‚",
                "message_id": f"assistant-{idx}",
                "turn_id": f"turn-{idx}",
                "context_epoch": 0,
            },
        ])
        result = await HeartbeatEngine.on_session_end(list(messages), "delta-growth-test")
        assert result["diary_written"] is True

    diary = AgentManager._memory_dir() / f"{time.strftime('%Y-%m-%d')}.md"
    text = diary.read_text(encoding="utf-8")
    assert text.count("Session Delta") == 20
    assert text.count("ç¬¬ 0 è½® delta") == 1
    assert diary.stat().st_size < 24 * 1024


@pytest.mark.asyncio
async def test_memory_ingestion_llm_json_validation(monkeypatch):
    from app.agents.memory_ingestion import MemoryIngestionEngine

    async def fake_extract(cls, texts, *, session_id):
        return [
            {
                "memory_type": "semantic",
                "content": "User prefers concise memory summaries.",
                "confidence": 0.88,
                "canonical_key": "preference:memory-summary-style",
                "entities": ["memory summaries"],
                "event_time": "",
                "ttl_hint": "",
            },
            {
                "memory_type": "identity",
                "content": "Low confidence identity fact.",
                "confidence": 0.7,
                "canonical_key": "identity:test",
            },
            {
                "memory_type": "semantic",
                "content": "api_key should not be stored",
                "confidence": 0.95,
                "canonical_key": "secret:test",
            },
            {
                "memory_type": "semantic",
                "content": "Skipped item",
                "confidence": 0.95,
                "skip_reason": "not durable",
            },
        ]

    monkeypatch.setattr(MemoryIngestionEngine, "extract_with_llm", classmethod(fake_extract))
    items = await MemoryIngestionEngine.extract_memory_candidates(
        [{"role": "user", "content": "è¯·è®°ä½ï¼šæˆ‘å–œæ¬¢ç®€æ´çš„è®°å¿†æ‘˜è¦ã€‚"}],
        session_id="extract-test",
    )

    assert len(items) == 1
    assert items[0]["canonical_key"] == "preference:memory-summary-style"
    assert items[0]["from_llm"] is True


@pytest.mark.asyncio
async def test_memory_ingestion_invalid_llm_json_falls_back(monkeypatch):
    from app.agents.memory_ingestion import MemoryIngestionEngine

    async def fake_extract(cls, texts, *, session_id):
        return None

    monkeypatch.setattr(MemoryIngestionEngine, "extract_with_llm", classmethod(fake_extract))
    items = await MemoryIngestionEngine.extract_memory_candidates(
        [{"role": "user", "content": "è¯·è®°ä½ï¼šä»¥åŽé»˜è®¤å…ˆåŽ»é‡å†å†™è®°å¿†ã€‚"}],
        session_id="fallback-test",
    )

    assert len(items) == 1
    assert items[0]["from_llm"] is False
    assert items[0]["confidence"] >= 0.8


@pytest.mark.asyncio
async def test_heartbeat_updates_same_session_handoff_instead_of_appending(tmp_path, monkeypatch):
    monkeypatch.setattr(AgentManager, "AGENTS_DIR", tmp_path / "AGENTS")
    monkeypatch.setattr(HeartbeatEngine, "_should_trigger_dream", classmethod(lambda cls, **kwargs: False))

    await HeartbeatEngine.on_session_end(
        [
            {"role": "user", "content": "请记住：第一版 handoff 内容。"},
            {"role": "assistant", "content": "我会写第一版交接。"},
        ],
        "handoff-upsert-test",
    )
    await HeartbeatEngine.on_session_end(
        [
            {"role": "user", "content": "请记住：第二版 handoff 内容。"},
            {"role": "assistant", "content": "我会更新交接，不追加重复项。"},
        ],
        "handoff-upsert-test",
    )

    from app.agents.memory_os import get_memory_os

    items = get_memory_os().list_items(memory_type="working", source="heartbeat", limit=20)
    handoffs = [item for item in items if "handoff-upsert-test" in item["source_ref"]]
    assert len(handoffs) == 1
    assert "第二版" in handoffs[0]["content"]


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

    async def fake_heartbeat(messages, session_id, agent_type="personal"):
        called["session_id"] = session_id
        called["messages"] = messages
        called["agent_type"] = agent_type
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
    assert called["agent_type"] == "personal"
    heartbeat_release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_session_runtime_publishes_done_at_run_completed_boundary():
    from app.agent import AgentSession
    from app.session_runtime import SessionRuntime

    session = AgentSession("gpt-4o", session_id="runtime-fast-done-test", agent_type="coding")
    runtime = SessionRuntime(session.session_id)
    queue = runtime.subscribe()
    tail_release = asyncio.Event()

    async def run_factory():
        yield {"type": "run_completed", "data": {"status": "completed"}}
        await tail_release.wait()

    await runtime.start(session, run_factory)
    first = await asyncio.wait_for(queue.get(), timeout=1)
    second = await asyncio.wait_for(queue.get(), timeout=1)

    assert first["type"] == "run_completed"
    assert second["type"] == "done"
    assert runtime.is_running is True

    tail_release.set()
    await asyncio.wait_for(runtime._task, timeout=1)
    assert runtime.is_running is False


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
    HeartbeatEngine.mark_dream_complete()

    assert HeartbeatEngine._should_trigger_dream() is False
