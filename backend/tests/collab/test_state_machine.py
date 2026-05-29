"""Tests for CollaborationStateMachine — P3 Eval Harness.

Covers:
- Valid transition sequences
- Invalid transitions raise ValueError
- Pause → resume cycle
- Phase history recording
"""
from __future__ import annotations

import uuid

import pytest

from app.collaboration.state_machine import CollaborationStateMachine, list_phase_history


@pytest.fixture
def sm():
    run_id = f"sm_test_{uuid.uuid4().hex[:8]}"
    return CollaborationStateMachine(run_id)


class TestCollaborationStateMachine:
    def test_initial_phase_is_pending(self, sm):
        assert sm.phase() == "pending"

    def test_valid_full_sequence(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("completed")
        assert sm.phase() == "completed"

    def test_valid_plan_sequence(self, sm):
        sm.transition("analyzing")
        sm.transition("planning")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("completed")
        assert sm.phase() == "completed"

    def test_valid_critic_sequence(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("critiquing")
        sm.transition("completed")
        assert sm.phase() == "completed"

    def test_invalid_transition_raises(self, sm):
        sm.transition("analyzing")
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition("completed")  # analyzing → completed is not valid

    def test_transition_from_completed_raises(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("completed")
        with pytest.raises(ValueError):
            sm.transition("analyzing")  # completed has no outgoing transitions

    def test_can_pause_from_executing(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        assert sm.can_pause() is True

    def test_cannot_pause_from_pending(self, sm):
        assert sm.can_pause() is False

    def test_cannot_pause_from_completed(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("completed")
        assert sm.can_pause() is False

    def test_pause_then_resume(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        assert sm.phase() == "executing"
        sm.transition("paused")
        assert sm.phase() == "paused"
        sm.resume()
        assert sm.phase() == "executing"

    def test_pause_from_awaiting_user_resumes_to_executing(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("awaiting_user")
        sm.transition("paused")
        sm.resume()
        assert sm.phase() == "executing"

    def test_resume_from_non_paused_raises(self, sm):
        sm.transition("analyzing")
        with pytest.raises(ValueError, match="Cannot resume"):
            sm.resume()

    def test_transition_to_failed(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("failed")
        assert sm.phase() == "failed"

    def test_phase_history_length(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("completed")
        history = list_phase_history(sm.run_id)
        assert len(history) >= 4

    def test_phase_history_records_phases_in_order(self, sm):
        sm.transition("analyzing")
        sm.transition("executing")
        history = list_phase_history(sm.run_id)
        phases = [h["phase"] for h in history]
        assert phases == ["analyzing", "executing"]

    def test_transition_with_note(self, sm):
        sm.transition("analyzing", note="starting analysis")
        history = list_phase_history(sm.run_id)
        assert any("starting analysis" in h["note"] for h in history)
