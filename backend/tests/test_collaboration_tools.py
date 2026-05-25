"""Regression tests for collaboration management tools (P1 fixes).

P1-1: ``PauseCodingRunTool`` must report the phase the run was paused FROM,
      not the post-transition phase (which is tautologically 'paused').
P1-4: ``cancel_workers_for_session`` must respect ``run_id_filter`` so that
      cancelling one collaboration run does not kill unrelated dispatch
      workers running under the same Personal session.
"""
from __future__ import annotations

import threading
import uuid
from unittest.mock import MagicMock

import pytest

from app.collaboration import manager
from app.collaboration.state_machine import CollaborationStateMachine
from app.tools import worker_tool
from app.tools.collaboration_tool import PauseCodingRunTool


@pytest.fixture()
def isolated_collaboration_db(tmp_path, monkeypatch):
    conn = getattr(manager._conn_local, "conn", None)
    if conn is not None:
        conn.close()
    monkeypatch.setattr(manager, "DB_PATH", tmp_path / "collaboration.db")
    monkeypatch.setattr(manager, "_conn_local", threading.local())
    yield
    conn = getattr(manager._conn_local, "conn", None)
    if conn is not None:
        conn.close()


@pytest.mark.asyncio
async def test_pause_coding_run_reports_previous_phase(isolated_collaboration_db):
    """Sm.phase() is read AFTER transition in the legacy code, so the
    output string always said 'Phase was: paused'. After the fix, the
    response must reflect the phase the run was actually paused FROM."""
    # manager.create_run auto-transitions to 'analyzing', so we only need
    # to drive it forward to 'executing' before pausing.
    run = manager.create_run(
        session_id=f"pause_test_{uuid.uuid4().hex[:6]}",
        goal="pause regression check",
        mode="execute",
        project_path="",
    )
    sm = CollaborationStateMachine(run.run_id)
    assert sm.phase() == "analyzing"
    sm.transition("executing")
    assert sm.phase() == "executing"

    tool = PauseCodingRunTool()
    result = await tool.execute(run_id=run.run_id, reason="probe")

    assert not result.error
    assert "Phase was: executing" in (result.output or "")
    assert "Phase was: paused" not in (result.output or "")
    # Side effect: state machine is now actually at 'paused'.
    assert sm.phase() == "paused"


@pytest.mark.asyncio
async def test_pause_coding_run_rejects_when_cannot_pause(isolated_collaboration_db):
    """If the run is in a non-pausable phase (e.g. 'completed'), the tool
    must surface the pre-transition phase in the error message rather than
    silently 'pausing' from a terminal state."""
    run = manager.create_run(
        session_id=f"pause_terminal_{uuid.uuid4().hex[:6]}",
        goal="terminal pause check",
        mode="execute",
        project_path="",
    )
    sm = CollaborationStateMachine(run.run_id)
    # create_run already put us in 'analyzing'; drive on to a terminal phase.
    sm.transition("executing")
    sm.transition("verifying")
    sm.transition("completed")

    tool = PauseCodingRunTool()
    result = await tool.execute(run_id=run.run_id)

    assert result.error is not None
    assert "completed" in result.error
    assert sm.phase() == "completed"  # untouched


def test_cancel_workers_for_session_respects_run_id_filter(monkeypatch):
    """A coding run cancellation must only stop workers belonging to that
    run, leaving unrelated dispatch_worker / dispatch_parallel tasks
    running in the same Personal session."""
    session_id = f"cancel_filter_{uuid.uuid4().hex[:6]}"

    worker_a = MagicMock()
    worker_a.run_id = "run_a"
    worker_a.cancel_event.return_value = None

    worker_b = MagicMock()
    worker_b.run_id = "run_b"
    worker_b.cancel_event.return_value = None

    monkeypatch.setitem(
        worker_tool._active_workers,
        session_id,
        {"wid_a": (worker_a, None), "wid_b": (worker_b, None)},
    )
    try:
        worker_tool.cancel_workers_for_session(session_id, run_id_filter="run_a")
        worker_a.cancel.assert_called_once()
        worker_b.cancel.assert_not_called()
    finally:
        worker_tool._active_workers.pop(session_id, None)


def test_cancel_workers_for_session_no_filter_cancels_all(monkeypatch):
    """Legacy behavior preserved: omitting ``run_id_filter`` (or passing
    empty string) cancels every worker registered under the session."""
    session_id = f"cancel_all_{uuid.uuid4().hex[:6]}"

    worker_a = MagicMock()
    worker_a.run_id = "run_a"
    worker_a.cancel_event.return_value = None
    worker_b = MagicMock()
    worker_b.run_id = "run_b"
    worker_b.cancel_event.return_value = None

    monkeypatch.setitem(
        worker_tool._active_workers,
        session_id,
        {"wid_a": (worker_a, None), "wid_b": (worker_b, None)},
    )
    try:
        worker_tool.cancel_workers_for_session(session_id)
        worker_a.cancel.assert_called_once()
        worker_b.cancel.assert_called_once()
    finally:
        worker_tool._active_workers.pop(session_id, None)
