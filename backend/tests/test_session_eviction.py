from app import agent as agent_mod
from app.agent import AgentSession, MAX_LIVE_SESSIONS, _evict_if_needed, _sessions


def _make_session(session_id: str, content_len: int = 0) -> AgentSession:
    session = AgentSession(model_id="gpt-4o", session_id=session_id)
    if content_len:
        session.messages = [{"role": "user", "content": "x" * content_len}]
    return session


def test_estimated_memory_bytes_counts_content():
    session = _make_session("mem-est")
    session.messages = [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": [{"type": "text", "text": "y" * 100}]},
    ]
    # 11 chars + 100 chars of block text.
    assert session.estimated_memory_bytes() >= 111


def test_evict_if_needed_respects_count_cap():
    _sessions.clear()
    try:
        for i in range(MAX_LIVE_SESSIONS + 5):
            _sessions[f"s{i}"] = _make_session(f"s{i}")
        _evict_if_needed()
        assert len(_sessions) <= MAX_LIVE_SESSIONS
        # Least-recently-used (oldest) dropped, newest retained.
        assert "s0" not in _sessions
        assert f"s{MAX_LIVE_SESSIONS + 4}" in _sessions
    finally:
        _sessions.clear()


def test_evict_if_needed_size_cap(monkeypatch):
    _sessions.clear()
    monkeypatch.setattr(agent_mod, "MAX_LIVE_TOTAL_BYTES", 1000)
    try:
        for i in range(4):
            _sessions[f"big{i}"] = _make_session(f"big{i}", content_len=600)
        _evict_if_needed()
        total = sum(s.estimated_memory_bytes() for s in _sessions.values())
        # Evicted down until under the byte budget (or only one session left).
        assert total <= 1000 or len(_sessions) == 1
        assert len(_sessions) < 4
    finally:
        _sessions.clear()
