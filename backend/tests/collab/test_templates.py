"""Tests for ``apply_template`` (P1-2 fix).

The legacy logic sniffed ``packet.budget.max_iterations == 30`` to decide
"caller did not set a budget" — brittle (silently breaks if defaults shift,
silently overrides callers who explicitly pass 30). The fix introduces a
``budget_explicit`` flag on ``TaskPacket`` that callers set when they pass
a custom budget.
"""
from __future__ import annotations

from app.collaboration.models import TaskBudget, TaskPacket
from app.collaboration.templates import apply_template


def test_apply_template_overrides_default_budget_when_not_explicit():
    """Default-constructed packet (budget_explicit=False) should accept the
    template's tuned budget."""
    packet = TaskPacket(goal="example bug")
    assert packet.budget_explicit is False

    apply_template(packet, "bugfix")

    # bugfix template uses TaskBudget(max_iterations=20, max_seconds=300)
    assert packet.budget.max_iterations == 20
    assert packet.budget.max_seconds == 300


def test_apply_template_respects_explicit_budget():
    """A caller-supplied budget (budget_explicit=True) must not be touched."""
    explicit = TaskBudget(max_iterations=99, max_seconds=999)
    packet = TaskPacket(goal="x", budget=explicit, budget_explicit=True)

    apply_template(packet, "bugfix")

    assert packet.budget.max_iterations == 99
    assert packet.budget.max_seconds == 999


def test_apply_template_respects_explicit_budget_matching_old_default():
    """Regression: legacy code sniffed `max_iterations == 30` as 'caller
    did not set'. An explicit budget that *happens* to equal 30 must still
    be respected when budget_explicit=True."""
    explicit = TaskBudget(max_iterations=30, max_seconds=600)
    packet = TaskPacket(goal="x", budget=explicit, budget_explicit=True)

    apply_template(packet, "bugfix")

    assert packet.budget.max_iterations == 30
    assert packet.budget.max_seconds == 600


def test_apply_template_overrides_non_budget_fields_only_when_empty():
    """Sanity: existing field-level overrides (acceptance_criteria,
    constraints, allowed_tools) keep their original semantics — populated
    fields are preserved, empty ones get the template defaults."""
    packet = TaskPacket(
        goal="x",
        acceptance_criteria=["caller criterion"],
        constraints=["caller constraint"],
    )
    apply_template(packet, "bugfix")
    assert packet.acceptance_criteria == ["caller criterion"]
    assert packet.constraints == ["caller constraint"]


def test_apply_template_no_op_for_unknown_template():
    """Unknown template name leaves the packet untouched (not an error)."""
    packet = TaskPacket(goal="x")
    original_budget = packet.budget.model_copy()
    apply_template(packet, "no_such_template")
    assert packet.budget.max_iterations == original_budget.max_iterations
    assert packet.acceptance_criteria == []
