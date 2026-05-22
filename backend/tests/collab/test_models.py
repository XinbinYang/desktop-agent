"""Tests for collaboration models contract — P0 Eval Harness."""
from __future__ import annotations

import pytest
from typing import Any, Dict

from app.collaboration.models import (
    ArtifactRef,
    CollaborationRun,
    CollaborationTask,
    EvidenceEntry,
    ResultPacket,
    TaskBudget,
    TaskInvariant,
    TaskPacket,
)


class TestTaskBudget:
    def test_defaults(self):
        b = TaskBudget()
        assert b.max_iterations == 30
        assert b.max_seconds == 600
        assert b.max_input_tokens == 200_000
        assert b.on_exceed == "ask_user"

    def test_custom_values(self):
        b = TaskBudget(max_iterations=10, on_exceed="stop")
        assert b.max_iterations == 10
        assert b.on_exceed == "stop"

    def test_on_exceed_escalate(self):
        b = TaskBudget(on_exceed="escalate")
        assert b.on_exceed == "escalate"


class TestTaskInvariant:
    def test_required_description(self):
        inv = TaskInvariant(description="Do not modify .env")
        assert inv.description == "Do not modify .env"
        assert inv.detector is None

    def test_with_detector(self):
        inv = TaskInvariant(description="No force push", detector="check_git_history")
        assert inv.detector == "check_git_history"


class TestEvidenceEntry:
    def test_command_entry(self):
        e = EvidenceEntry(kind="command", label="pytest", command="pytest tests/", exit_code=0)
        assert e.kind == "command"
        assert e.exit_code == 0
        assert e.output_excerpt == ""

    def test_defaults(self):
        e = EvidenceEntry(kind="diff", label="git diff")
        assert e.command == ""
        assert e.exit_code is None
        assert e.output_ref is None

    def test_output_excerpt_truncation(self):
        long_output = "x" * 3000
        e = EvidenceEntry(kind="test", label="run tests", output_excerpt=long_output[:2048])
        assert len(e.output_excerpt) == 2048


class TestTaskPacket:
    def test_minimal_construction(self):
        p = TaskPacket(goal="Fix bug")
        assert p.goal == "Fix bug"
        assert p.mode == "consult"
        assert p.owner == "coding"
        assert p.created_by == "personal"

    def test_backward_compat_no_new_fields(self, sample_task_packet_data):
        """旧格式（无新字段）能正常反序列化，新字段有合理默认值。"""
        p = TaskPacket(**sample_task_packet_data)
        assert p.goal == "Fix the login bug in auth.py"
        # New fields have defaults
        assert isinstance(p.budget, TaskBudget)
        assert p.budget.max_iterations == 30
        assert p.invariants == []
        assert p.expected_output_schema is None
        assert p.prior_attempts == []
        assert p.parent_task_id is None
        assert p.correlation_key is None

    def test_with_budget(self):
        p = TaskPacket(
            goal="Refactor",
            budget=TaskBudget(max_iterations=10, on_exceed="stop"),
        )
        assert p.budget.max_iterations == 10

    def test_with_invariants(self):
        p = TaskPacket(
            goal="Deploy",
            invariants=[TaskInvariant(description="No .env changes")],
        )
        assert len(p.invariants) == 1
        assert p.invariants[0].description == "No .env changes"

    def test_new_task_modes(self):
        for mode in ("plan_then_execute", "critic", "verify_only"):
            p = TaskPacket(goal="test", mode=mode)
            assert p.mode == mode

    def test_prior_attempts(self):
        p = TaskPacket(goal="Fix", prior_attempts=["tried X", "tried Y"])
        assert len(p.prior_attempts) == 2

    def test_correlation_key(self):
        p = TaskPacket(goal="Fix", correlation_key="bug-123")
        assert p.correlation_key == "bug-123"

    def test_owner_is_string(self):
        """owner 是 str 类型，支持未来专家注册。"""
        p = TaskPacket(goal="Fix", owner="coding")
        assert isinstance(p.owner, str)
        # 未来专家也可以注册
        p2 = TaskPacket(goal="Fix", owner="qa_agent")
        assert p2.owner == "qa_agent"

    def test_full_budget_from_fixture(self):
        from tests.collab.conftest import FIXTURES_DIR
        import json
        with open(FIXTURES_DIR / "sample_packets.json") as f:
            data = json.load(f)
        p = TaskPacket(**data["with_budget"])
        assert p.budget.max_iterations == 15
        assert p.invariants[0].description == "Do not modify .env files"
        assert p.prior_attempts[0].startswith("Tried renaming")
        assert p.correlation_key == "refactor-auth-2025"


class TestResultPacket:
    def test_defaults(self):
        r = ResultPacket()
        assert r.status == "pass"
        assert r.confidence == 1.0
        assert r.needs_human_decision == []
        assert r.follow_up_tasks == []
        assert r.evidence == []
        assert r.cost == {}
        assert r.invariants_violated == []

    def test_backward_compat_minimal(self):
        """旧消费方只传 status/summary 仍能工作。"""
        r = ResultPacket(status="fail", summary="Tests failed.")
        assert r.status == "fail"
        assert r.evidence == []

    def test_with_evidence(self):
        e = EvidenceEntry(kind="command", label="pytest", exit_code=0)
        r = ResultPacket(evidence=[e])
        assert len(r.evidence) == 1
        assert r.evidence[0].exit_code == 0

    def test_needs_human_decision(self):
        r = ResultPacket(needs_human_decision=["Should we bump the major version?"])
        assert len(r.needs_human_decision) == 1

    def test_follow_up_tasks(self):
        follow_up = TaskPacket(goal="Write docs for new feature")
        r = ResultPacket(follow_up_tasks=[follow_up])
        assert len(r.follow_up_tasks) == 1
        assert r.follow_up_tasks[0].goal == "Write docs for new feature"

    def test_cost_dict(self):
        r = ResultPacket(cost={"tokens_in": 1000.0, "tokens_out": 500.0, "seconds": 12.5})
        assert r.cost["tokens_in"] == 1000.0

    def test_invariants_violated(self):
        r = ResultPacket(invariants_violated=["Modified .env"])
        assert r.invariants_violated == ["Modified .env"]


class TestCollaborationRun:
    def test_defaults(self):
        run = CollaborationRun(run_id="r1", session_id="s1")
        assert run.status == "running"
        assert run.correlation_key is None

    def test_correlation_key(self):
        run = CollaborationRun(run_id="r1", session_id="s1", correlation_key="feature-x")
        assert run.correlation_key == "feature-x"

    def test_source_target_agent_str(self):
        """source_agent / target_agent 现在是 str，支持未来专家。"""
        run = CollaborationRun(run_id="r1", session_id="s1", source_agent="personal", target_agent="qa_agent")
        assert run.target_agent == "qa_agent"
