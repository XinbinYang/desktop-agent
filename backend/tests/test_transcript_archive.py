"""Tests for per-session transcript archiving (P1-2).

When self.messages exceeds MAX_RESIDENT_MESSAGES and a compaction boundary
exists, _archive_excess_messages() evicts the oldest pre-boundary messages to
an append-only .archive.jsonl file so resident memory stays bounded.
"""
import json
import pytest

from app import agent as agent_mod
from app.agent import AgentSession


def _make_session(session_id: str) -> AgentSession:
    s = AgentSession(model_id="gpt-4o", session_id=session_id)
    # Remove the auto-injected system message so test message indices are
    # predictable (system prompt is re-added on load via _refresh_system_prompt).
    s.messages.clear()
    return s


def _fill_messages(session: AgentSession, count: int, *, start: int = 0) -> None:
    for i in range(start, start + count):
        session.messages.append({
            "role": "user",
            "content": f"msg {i}",
            "message_id": f"msg_{i:06d}",
        })


def _set_compaction_boundary(session: AgentSession, message_id: str) -> None:
    """Simulate a completed compaction recorded at the given message_id."""
    session.compaction_summary = "earlier turns summarised"
    session.compaction_state = {
        "version": 1,
        "compacted_through_message_id": message_id,
        "compacted_through_checkpoint_id": "",
        "compacted_turn_count": 3,
        "last_compacted_at": "2026-01-01T00:00:00",
        "last_auto_error": "",
    }


class TestArchiveExcessMessages:
    def test_no_op_when_within_resident_limit(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 20)
        s = _make_session("arc-noop")
        _fill_messages(s, 15)
        _set_compaction_boundary(s, "msg_000009")

        s._archive_excess_messages()

        assert len(s.messages) == 15
        assert s._archived_message_count == 0

    def test_no_op_when_no_compaction_boundary(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 10)
        s = _make_session("arc-noboundary")
        _fill_messages(s, 15)
        # No compaction_summary → boundary is None → unsafe to archive

        s._archive_excess_messages()

        assert len(s.messages) == 15
        assert s._archived_message_count == 0

    def test_archives_messages_before_boundary(self, monkeypatch, tmp_path):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 10)
        monkeypatch.setattr(agent_mod, "SESSIONS_DIR", tmp_path)
        s = _make_session("arc-basic")
        _fill_messages(s, 15)  # indices 0..14, message_ids msg_000000..msg_000014
        _set_compaction_boundary(s, "msg_000009")  # boundary at index 9

        # excess = 15 - 10 = 5; archive_end = min(9, 5) = 5
        s._archive_excess_messages()

        assert len(s.messages) == 10
        assert s._archived_message_count == 5
        assert s.messages[0]["message_id"] == "msg_000005"

        archive_path = tmp_path / "arc-basic.archive.jsonl"
        assert archive_path.exists()
        archived = [json.loads(line) for line in archive_path.read_text(encoding="utf-8").splitlines()]
        assert len(archived) == 5
        assert archived[0]["message_id"] == "msg_000000"
        assert archived[-1]["message_id"] == "msg_000004"

    def test_boundary_message_stays_resident(self, monkeypatch, tmp_path):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 5)
        monkeypatch.setattr(agent_mod, "SESSIONS_DIR", tmp_path)
        s = _make_session("arc-boundary")
        _fill_messages(s, 8)  # 8 msgs, indices 0..7
        _set_compaction_boundary(s, "msg_000003")  # boundary at index 3

        # excess = 8 - 5 = 3; archive_end = min(3, 3) = 3 → archive 0..2
        s._archive_excess_messages()

        assert s.messages[0]["message_id"] == "msg_000003"  # boundary msg is first resident
        assert len(s.messages) == 5

    def test_archive_appended_across_two_saves(self, monkeypatch, tmp_path):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 8)
        monkeypatch.setattr(agent_mod, "SESSIONS_DIR", tmp_path)
        s = _make_session("arc-append")
        _fill_messages(s, 12)  # 12 msgs
        _set_compaction_boundary(s, "msg_000010")  # boundary at index 10

        # First pass: excess = 4; archive_end = min(10, 4) = 4
        s._archive_excess_messages()
        assert s._archived_message_count == 4
        assert len(s.messages) == 8

        # Add 5 more messages; boundary message (msg_000010) is now at resident index 6
        _fill_messages(s, 5, start=20)
        # Refresh boundary to the same logical message
        _set_compaction_boundary(s, "msg_000010")

        # Second pass: total = 13, excess = 5; boundary at resident index 6
        # archive_end = min(6, 5) = 5
        s._archive_excess_messages()
        assert s._archived_message_count == 9  # 4 + 5

        archive_path = tmp_path / "arc-append.archive.jsonl"
        lines = archive_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 9  # all archived messages in file

    def test_archived_count_round_trips_through_save_and_load(self, monkeypatch, tmp_path):
        monkeypatch.setattr(agent_mod, "MAX_RESIDENT_MESSAGES", 10)
        monkeypatch.setattr(agent_mod, "SESSIONS_DIR", tmp_path)
        s = _make_session("arc-persist")
        _fill_messages(s, 15)
        _set_compaction_boundary(s, "msg_000009")

        # _save() calls _build_save_payload() which calls _archive_excess_messages()
        s._save()

        assert s._archived_message_count == 5
        assert len(s.messages) == 10

        loaded = AgentSession.load("arc-persist")
        assert loaded is not None
        assert loaded._archived_message_count == 5
        # 10 user messages + 1 re-injected system message from _refresh_system_prompt
        user_msgs = [m for m in loaded.messages if m.get("role") != "system"]
        assert len(user_msgs) == 10
