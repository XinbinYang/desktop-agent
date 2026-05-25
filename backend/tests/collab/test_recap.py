"""Tests for RunRecap — P2 Eval Harness.

Covers:
- recap_from_events extracts correct fields from fixture events
- Large event streams (50+) produce non-empty recap
- one_liner length capped at 100 characters
- evidence_ledger correctly extracts command/test/review events
- Key decision extraction from Chinese and English content
- Changed files from file-write tool calls
- Failure summary from failed runs
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.collaboration.recap import RunRecap, recap_from_events

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_events(key: str) -> List[Dict[str, Any]]:
    with open(FIXTURES_DIR / "sample_events.json", encoding="utf-8") as f:
        return json.load(f)[key]


class TestRecapFromEvents:
    def test_basic_fields_from_execute_with_tools(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        assert isinstance(recap, RunRecap)
        assert recap.run_id == "test_run_001"
        assert recap.trace_anchor == "test_run_001"
        assert recap.one_liner == "Login bug fixed."

    def test_one_liner_under_100_chars(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        assert len(recap.one_liner) <= 100

    def test_evidence_ledger_contains_command(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        kinds = [e.kind for e in recap.evidence_ledger]
        assert "command" in kinds

    def test_evidence_ledger_contains_diff(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        kinds = [e.kind for e in recap.evidence_ledger]
        assert "diff" in kinds

    def test_evidence_ledger_contains_test(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        kinds = [e.kind for e in recap.evidence_ledger]
        assert "test" in kinds

    def test_evidence_ledger_contains_review(self):
        events = _load_events("execute_with_tools")
        recap = recap_from_events("test_run_001", events)
        kinds = [e.kind for e in recap.evidence_ledger]
        assert "review" in kinds

    def test_failed_run_has_failure_summary(self):
        events = _load_events("fail_run")
        recap = recap_from_events("test_fail", events)
        assert recap.failure_summary is not None
        assert "Tests failed" in recap.failure_summary

    def test_pass_run_no_failure_summary(self):
        events = _load_events("pass_run")
        recap = recap_from_events("test_pass", events)
        assert recap.failure_summary is None

    def test_empty_events_returns_empty_fields(self):
        recap = recap_from_events("test_empty", [])
        assert recap.one_liner == ""
        assert recap.key_decisions == []
        assert recap.changed_files == []
        assert recap.evidence_ledger == []
        assert recap.failure_summary is None

    def test_changed_files_from_file_write_tool(self):
        events = [
            {"type": "tool_call", "data": {
                "name": "file_write",
                "args": {"path": "src/auth.py"},
                "result": "Written.",
            }},
            {"type": "tool_call", "data": {
                "name": "file_edit",
                "args": {"file_path": "src/main.py"},
                "result": "Edited.",
            }},
            {"type": "run_completed", "data": {"status": "completed", "summary": "Done."}},
        ]
        recap = recap_from_events("test_write", events)
        assert "src/auth.py" in recap.changed_files
        assert "src/main.py" in recap.changed_files

    def test_key_decisions_from_english(self):
        events = [
            {"type": "content", "data": {"text": "We decided to use JWT for authentication."}},
            {"type": "content", "data": {"text": "The chosen approach is to refactor the module."}},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        recap = recap_from_events("test_decisions", events)
        assert len(recap.key_decisions) >= 1
        assert any("decided" in d.lower() for d in recap.key_decisions)

    def test_key_decisions_from_chinese(self):
        events = [
            {"type": "content", "data": {"text": "我们决定采用 JWT 方案进行认证。"}},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        recap = recap_from_events("test_decisions_cn", events)
        assert len(recap.key_decisions) >= 1
        assert any("决定" in d or "方案" in d for d in recap.key_decisions)

    def test_large_event_stream(self):
        """50 mock sub-events should produce a non-empty recap."""
        events: List[Dict[str, Any]] = [
            {"type": "tool_call", "data": {
                "name": "shell_execute",
                "args": {"command": "pytest"},
                "result": "exit_code: 0\npass",
            }}
            for _ in range(30)
        ]
        events.extend([
            {"type": "tool_call", "data": {
                "name": "file_write",
                "args": {"path": f"src/mod{i}.py"},
                "result": "OK",
            }}
            for i in range(15)
        ])
        events.append(
            {"type": "content", "data": {"text": "We decided to implement the feature."}}
        )
        events.append(
            {"type": "run_completed", "data": {"status": "completed", "summary": "Large refactor done."}}
        )

        recap = recap_from_events("test_large", events)
        assert recap.one_liner == "Large refactor done."
        assert len(recap.one_liner) <= 100
        assert len(recap.changed_files) > 0
        assert len(recap.evidence_ledger) > 0
        assert len(recap.key_decisions) >= 1

    def test_one_liner_from_collaboration_run_created(self):
        events = [
            {"type": "collaboration_run_created", "data": {"goal": "修复用户登录相关的认证 bug"}},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        recap = recap_from_events("test_goal_cn", events)
        assert "登录" in recap.one_liner

    def test_evidence_ledger_deduplicates_commands(self):
        """Multiple shell_execute calls each produce their own evidence entry."""
        events = [
            {"type": "tool_call", "data": {
                "name": "shell_execute", "args": {"command": "pytest tests/ -x"},
                "result": "exit_code: 0\npass", "tool_call_id": "a",
            }},
            {"type": "tool_call", "data": {
                "name": "shell_execute", "args": {"command": "npm test"},
                "result": "exit_code: 0\npass", "tool_call_id": "b",
            }},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        recap = recap_from_events("test_dedup", events)
        commands = [e for e in recap.evidence_ledger if e.kind == "command"]
        assert len(commands) == 2
        assert any("pytest" in e.command for e in commands)
        assert any("npm test" in e.command for e in commands)


class TestWeeklyJournal:
    """P1-3 regression: weekly journal must use the CURRENT week label,
    not the cutoff (which is `hours` in the past — for the default 168h
    window that wrote into *last* week's file)."""

    def test_journal_path_uses_current_week_label(self, tmp_path, monkeypatch):
        import sqlite3
        import time
        from app import runtime_paths
        from app.collaboration import recap

        # Redirect runtime_file so both the DB read and the journal write
        # land in the tmp directory — keeps the test hermetic.
        def fake_runtime_file(*parts):
            return tmp_path.joinpath(*parts)

        monkeypatch.setattr(runtime_paths, "runtime_file", fake_runtime_file)

        # Seed a fake collaboration_runs.db with one completed run.
        db_path = tmp_path / "data" / "collaboration_runs.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE collaboration_runs (run_id TEXT, status TEXT, "
            "mode TEXT, goal TEXT, summary TEXT, updated_at REAL)"
        )
        conn.execute(
            "INSERT INTO collaboration_runs VALUES (?, ?, ?, ?, ?, ?)",
            ("run_x", "completed", "execute", "test goal", "ok", time.time()),
        )
        conn.commit()
        conn.close()

        path = recap.write_weekly_journal(hours=24)

        assert path is not None, "expected a journal file to be written"
        expected_week = time.strftime("%Y-W%W", time.gmtime())
        assert expected_week in str(path), (
            f"journal path {path!r} should contain current week label "
            f"{expected_week!r} (not the cutoff's week)"
        )

    def test_journal_returns_none_when_no_runs(self, tmp_path, monkeypatch):
        """Empty DB → returns None, no file written."""
        import sqlite3
        from app import runtime_paths
        from app.collaboration import recap

        monkeypatch.setattr(
            runtime_paths, "runtime_file",
            lambda *parts: tmp_path.joinpath(*parts),
        )

        db_path = tmp_path / "data" / "collaboration_runs.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE collaboration_runs (run_id TEXT, status TEXT, "
            "mode TEXT, goal TEXT, summary TEXT, updated_at REAL)"
        )
        conn.commit()
        conn.close()

        assert recap.write_weekly_journal(hours=24) is None
