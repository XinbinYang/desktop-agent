"""Tests for collaboration executor — P0 Eval Harness."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.collaboration.executor import _extract_evidence, result_from_execute_events, run_execute_agent_events
from app.collaboration.models import EvidenceEntry, ResultPacket
from app.collaboration.models import TaskPacket

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_events(key: str) -> List[Dict[str, Any]]:
    with open(FIXTURES_DIR / "sample_events.json", encoding="utf-8") as f:
        return json.load(f)[key]


class TestExtractEvidence:
    def test_extracts_shell_execute(self):
        events = _load_events("execute_with_tools")
        evidence = _extract_evidence(events)
        commands = [e for e in evidence if e.kind == "command"]
        assert len(commands) >= 1
        assert commands[0].command == "pytest tests/ -x"

    def test_shell_execute_exit_code_parsed(self):
        events = _load_events("execute_with_tools")
        evidence = _extract_evidence(events)
        cmd_entries = [e for e in evidence if e.kind == "command"]
        assert cmd_entries[0].exit_code == 0

    def test_extracts_git_diff(self):
        events = _load_events("execute_with_tools")
        evidence = _extract_evidence(events)
        diffs = [e for e in evidence if e.kind == "diff"]
        assert len(diffs) >= 1

    def test_extracts_run_review(self):
        events = _load_events("execute_with_tools")
        evidence = _extract_evidence(events)
        reviews = [e for e in evidence if e.kind == "review"]
        assert len(reviews) >= 1

    def test_extracts_verify_project_as_test(self):
        events = _load_events("execute_with_tools")
        evidence = _extract_evidence(events)
        tests = [e for e in evidence if e.kind == "test"]
        assert len(tests) >= 1

    def test_output_excerpt_truncated_to_2048(self):
        long_output = "x" * 4000
        events = [{
            "type": "tool_call",
            "data": {
                "name": "shell_execute",
                "args": {"command": "echo hi"},
                "result": f"exit_code: 0\n{long_output}",
                "tool_call_id": "tc_long",
            }
        }]
        evidence = _extract_evidence(events)
        assert len(evidence) == 1
        assert len(evidence[0].output_excerpt) <= 2048

    def test_non_evidence_tools_ignored(self):
        events = [{
            "type": "tool_call",
            "data": {
                "name": "file_read",
                "args": {"path": "auth.py"},
                "result": "def login(): ...",
                "tool_call_id": "tc_read",
            }
        }]
        evidence = _extract_evidence(events)
        assert evidence == []

    def test_empty_events_returns_empty(self):
        assert _extract_evidence([]) == []

    def test_content_events_ignored(self):
        events = [{"type": "content", "data": {"text": "Some output"}}]
        assert _extract_evidence(events) == []


class TestResultFromExecuteEvents:
    def test_pass_run(self):
        events = _load_events("execute_with_tools")
        result = result_from_execute_events(events)
        assert result.status == "pass"
        assert result.verification_passed is True
        assert result.review_passed is True

    def test_fail_run_acceptance_string(self):
        """ACCEPTANCE: FAIL 字符串触发 fail 状态（向后兼容兜底）。"""
        events = _load_events("fail_run")
        result = result_from_execute_events(events)
        assert result.status == "fail"

    def test_fail_run_verification_false(self):
        """verification_passed=false 触发 fail 状态。"""
        events = [
            {"type": "content", "data": {"text": "Done."}},
            {"type": "run_completed", "data": {
                "status": "completed",
                "verification_passed": False,
                "review_passed": None,
            }}
        ]
        result = result_from_execute_events(events)
        assert result.status == "fail"

    def test_fail_run_completed_status_failed(self):
        """run_completed.status = 'failed' 触发 fail 状态。"""
        events = [
            {"type": "run_completed", "data": {
                "status": "failed",
                "verification_passed": None,
                "review_passed": None,
            }}
        ]
        result = result_from_execute_events(events)
        assert result.status == "fail"

    def test_fail_run_max_iterations(self):
        events = [
            {"type": "run_completed", "data": {
                "status": "max_iterations_reached",
                "verification_passed": None,
            }}
        ]
        result = result_from_execute_events(events)
        assert result.status == "fail"

    def test_evidence_populated_from_tool_calls(self):
        events = _load_events("execute_with_tools")
        result = result_from_execute_events(events)
        assert len(result.evidence) > 0

    def test_evidence_empty_for_pass_run_without_tools(self):
        events = _load_events("pass_run")
        result = result_from_execute_events(events)
        assert result.status == "fail"
        assert result.evidence == []

    def test_run_completed_boolean_without_evidence_does_not_satisfy_verification(self):
        events = _load_events("pass_run")
        result = result_from_execute_events(events, require_verification=True, require_review=False)
        assert result.status == "fail"
        assert any("Verification evidence" in blocker for blocker in result.blockers)

    def test_summary_from_content(self):
        events = [
            {"type": "content", "data": {"text": "Fixed the bug successfully."}},
            {"type": "run_completed", "data": {"status": "completed"}}
        ]
        result = result_from_execute_events(events)
        assert "Fixed the bug" in result.summary

    def test_summary_fallback_from_run_completed(self):
        events = [
            {"type": "run_completed", "data": {
                "status": "completed",
                "summary": "Fallback summary from completed event.",
            }}
        ]
        result = result_from_execute_events(events)
        assert "Fallback summary" in result.summary

    def test_empty_events_returns_fail(self):
        result = result_from_execute_events([])
        assert result.status == "fail"
        assert result.evidence == []

    def test_execute_requires_verification_evidence(self):
        events = [
            {"type": "content", "data": {"text": "Done. ACCEPTANCE: PASS"}},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        result = result_from_execute_events(events, require_verification=True, require_review=False)
        assert result.status == "fail"
        assert any("Verification evidence" in blocker for blocker in result.blockers)

    def test_verification_shell_command_without_exit_code_counts_when_not_failed(self):
        events = [
            {"type": "tool_call", "data": {"name": "shell_execute", "args": {"command": "npm run build"}, "result": "vite built in 2.0s"}},
            {"type": "content", "data": {"text": "Done. ACCEPTANCE: PASS"}},
            {"type": "run_completed", "data": {"status": "completed"}},
        ]
        result = result_from_execute_events(events, require_verification=True, require_review=False)
        assert result.status == "pass"

    def test_execute_requires_review_for_file_changes(self):
        events = [
            {"type": "tool_call", "data": {"name": "file_write", "args": {"path": "a.py"}, "result": "ok"}},
            {"type": "tool_call", "data": {"name": "verify_project", "args": {}, "result": "exit_code: 0\nok"}},
            {"type": "content", "data": {"text": "Done. ACCEPTANCE: PASS"}},
            {"type": "run_completed", "data": {"status": "completed", "verification_passed": True}},
        ]
        result = result_from_execute_events(events, require_verification=True, require_review=True)
        assert result.status == "fail"
        assert result.changed_files == ["a.py"]
        assert any("Review evidence" in blocker for blocker in result.blockers)

    def test_run_completed_review_boolean_without_evidence_does_not_satisfy_review(self):
        events = [
            {"type": "tool_call", "data": {"name": "file_write", "args": {"path": "a.py"}, "result": "ok"}},
            {"type": "tool_call", "data": {"name": "verify_project", "args": {}, "result": "exit_code: 0\nok"}},
            {"type": "content", "data": {"text": "Done. ACCEPTANCE: PASS"}},
            {"type": "run_completed", "data": {"status": "completed", "verification_passed": True, "review_passed": True}},
        ]
        result = result_from_execute_events(events, require_verification=True, require_review=True)
        assert result.status == "fail"
        assert any("Review evidence" in blocker for blocker in result.blockers)

    def test_result_packet_is_resultpacket_instance(self):
        result = result_from_execute_events([])
        assert isinstance(result, ResultPacket)


@pytest.mark.asyncio
async def test_delegated_execute_auto_builds_submitted_plan(monkeypatch):
    import app.agent as agent_module
    import app.collaboration.executor as executor

    class Todo:
        def model_dump(self):
            return {"id": "t1", "title": "Implement", "status": "in_progress"}

    class PlanState:
        phase = "idle"
        approved = False
        todos = [Todo()]

    class FakeCodingSession:
        last_instance = None

        def __init__(self, *args, **kwargs):
            self.plan_state = PlanState()
            self.inputs = []
            FakeCodingSession.last_instance = self

        def _save(self):
            pass

        def plan_event_payload(self):
            return {"phase": self.plan_state.phase, "approved": self.plan_state.approved}

        def build_plan(self):
            self.plan_state.phase = "executing"
            self.plan_state.approved = True
            return True

        async def run(self, user_input, image_base64=None, *, chat_mode=None, thinking_intensity=None):
            self.inputs.append(user_input)
            if len(self.inputs) == 1:
                self.plan_state.phase = "awaiting_approval"
                yield {"type": "plan_status", "data": {"phase": "awaiting_approval"}}
                yield {"type": "run_completed", "data": {"status": "completed"}}
                return
            self.plan_state.phase = "completed"
            yield {"type": "tool_call", "data": {"name": "verify_project", "args": {}, "result": "exit_code: 0\nok"}}
            yield {"type": "tool_call", "data": {"name": "run_review", "args": {}, "result": "No blocking findings."}}
            yield {"type": "content", "data": {"text": "Implemented. ACCEPTANCE: PASS"}}
            yield {"type": "run_completed", "data": {"status": "completed", "verification_passed": True, "review_passed": True}}

    monkeypatch.setattr(agent_module, "AgentSession", FakeCodingSession)
    monkeypatch.setattr(executor, "get_model_for_agent", lambda agent_type: "test-model")

    events = [
        event
        async for event in run_execute_agent_events(
            TaskPacket(goal="implement"),
            session_id="s1",
            run_id="r1",
            project_path="",
        )
    ]

    assert any(event["type"] == "collaboration_plan_auto_approved" for event in events)
    assert FakeCodingSession.last_instance.inputs[1] == "__plan_continue__"
    result = result_from_execute_events(events, require_verification=True, require_review=False)
    assert result.status == "pass"


@pytest.mark.asyncio
async def test_delegated_execute_waits_for_personal_clarification(monkeypatch):
    import app.agent as agent_module
    import app.collaboration.executor as executor
    from app.collaboration.bus import clear_clarification_answers, submit_clarification_answer

    class PlanState:
        phase = "idle"
        approved = False
        todos = []

    class FakeCodingSession:
        last_instance = None

        def __init__(self, *args, **kwargs):
            self.plan_state = PlanState()
            self.inputs = []
            self.collaboration_run_id = ""
            self.collaboration_task_id = ""
            FakeCodingSession.last_instance = self

        def _save(self):
            pass

        def plan_event_payload(self):
            return {"phase": self.plan_state.phase, "approved": self.plan_state.approved}

        def build_plan(self):
            return False

        async def run(self, user_input, image_base64=None, *, chat_mode=None, thinking_intensity=None):
            self.inputs.append(user_input)
            if len(self.inputs) == 1:
                yield {
                    "type": "collaboration_clarification_request",
                    "data": {
                        "request_id": "clar_test",
                        "question": "Use simple_return or log_return?",
                        "options": ["log_return", "simple_return"],
                    },
                }
                yield {"type": "run_completed", "data": {"status": "waiting_clarification"}}
                return
            yield {"type": "tool_call", "data": {"name": "verify_project", "args": {}, "result": "exit_code: 0\nok"}}
            yield {"type": "tool_call", "data": {"name": "run_review", "args": {}, "result": "No blocking findings."}}
            yield {"type": "content", "data": {"text": "Used log_return. ACCEPTANCE: PASS"}}
            yield {
                "type": "run_completed",
                "data": {"status": "completed", "verification_passed": True, "review_passed": True},
            }

    monkeypatch.setattr(agent_module, "AgentSession", FakeCodingSession)
    monkeypatch.setattr(executor, "get_model_for_agent", lambda agent_type: "test-model")
    clear_clarification_answers("r_clarify")
    await submit_clarification_answer("r_clarify", "Use log_return", request_id="clar_test")

    events = [
        event
        async for event in run_execute_agent_events(
            TaskPacket(goal="implement"),
            session_id="s1",
            run_id="r_clarify",
            task_id="ctask_clarify",
            project_path="",
        )
    ]

    assert any(event["type"] == "decision_required" for event in events)
    assert any(event["type"] == "collaboration_clarification_answer" for event in events)
    assert "Use log_return" in FakeCodingSession.last_instance.inputs[1]
    result = result_from_execute_events(events, require_verification=True, require_review=False)
    assert result.status == "pass"
    clear_clarification_answers("r_clarify")
