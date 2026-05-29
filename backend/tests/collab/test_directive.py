"""Tests for Collaboration Event Bus (inject_directive / poll_directive) — P3 Eval.

Covers:
- inject_directive → poll_directive returns the directive
- Empty queue returns None
- clear_directives drops pending directives
- Multiple directives queued and polled in order
"""
from __future__ import annotations

import pytest

from app.collaboration.bus import (
    clear_clarification_answers,
    clear_directives,
    get_directive_queue,
    inject_directive,
    poll_directive,
    submit_clarification_answer,
    wait_for_clarification_answer,
)


class TestDirectiveBus:
    async def test_inject_then_poll_returns_directive(self):
        await inject_directive("run_001", "focus on error handling")
        result = await poll_directive("run_001")
        assert result == "focus on error handling"
        clear_directives("run_001")

    async def test_empty_queue_returns_none(self):
        clear_directives("run_empty")
        result = await poll_directive("run_empty")
        assert result is None

    async def test_clear_directives_drops_pending(self):
        await inject_directive("run_002", "directive one")
        await inject_directive("run_002", "directive two")
        clear_directives("run_002")
        result = await poll_directive("run_002")
        assert result is None

    async def test_multiple_directives_in_order(self):
        clear_directives("run_003")
        await inject_directive("run_003", "first")
        await inject_directive("run_003", "second")
        await inject_directive("run_003", "third")
        assert await poll_directive("run_003") == "first"
        assert await poll_directive("run_003") == "second"
        assert await poll_directive("run_003") == "third"
        assert await poll_directive("run_003") is None
        clear_directives("run_003")

    async def test_get_directive_queue_creates_new_queue(self):
        q = get_directive_queue("run_new")
        assert q is not None
        clear_directives("run_new")

    async def test_submit_then_wait_for_clarification_answer(self):
        clear_clarification_answers("run_clarify")
        await submit_clarification_answer(
            "run_clarify",
            "Use log_return",
            request_id="clar_1",
        )

        result = await wait_for_clarification_answer(
            "run_clarify",
            request_id="clar_1",
            timeout=1,
        )

        assert result is not None
        assert result["answer"] == "Use log_return"
        assert result["request_id"] == "clar_1"
        clear_clarification_answers("run_clarify")
