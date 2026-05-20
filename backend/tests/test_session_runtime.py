"""Tests for SessionRuntime turn-completion semantics.

The key invariants under test:
  - wait_until_idle() returns as soon as the `done` event is published, even
    if the underlying _task is still doing trailing work (e.g. async save).
  - A new turn started while the previous task is in its post-done trailing
    work detaches the old task instead of cancelling it, so the trailing
    work (e.g. disk write) completes safely in background.
  - Explicit cancel()/terminate() still cancels mid-turn regardless of
    turn-completed state.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, AsyncIterator, Dict, List

import pytest

from app.session_runtime import SessionRuntime


def _fake_session(agent_type: str = "coding") -> Any:
    # SessionRuntime only touches: session.cancel(), session.agent_type,
    # session.heartbeat_transcript_messages(), session.session_id.
    return SimpleNamespace(
        session_id="t",
        agent_type=agent_type,
        cancel=lambda: None,
        heartbeat_transcript_messages=lambda: [],
    )


async def _drain_subscriber(queue: "asyncio.Queue[Dict[str, Any]]", target_type: str, timeout: float = 1.0) -> Dict[str, Any]:
    """Pull events from the queue until one matching target_type appears."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError(f"Did not see event '{target_type}' within timeout")
        ev = await asyncio.wait_for(queue.get(), timeout=remaining)
        if ev.get("type") == target_type:
            return ev


@pytest.mark.asyncio
async def test_wait_until_idle_returns_after_done_even_if_task_still_trailing():
    runtime = SessionRuntime("sess-1")
    session = _fake_session("coding")

    trailing_started = asyncio.Event()
    release_trailing = asyncio.Event()

    async def run_factory() -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "status", "data": {"status": "thinking"}}
        yield {"type": "run_completed", "data": {"status": "completed"}}
        # Simulate trailing work (e.g. _save_async still going) blocked behind
        # an event we control from the test.
        trailing_started.set()
        await release_trailing.wait()

    queue = runtime.subscribe()
    await runtime.start(session, run_factory)

    # `done` should appear shortly after run_completed.
    await _drain_subscriber(queue, "done")
    assert runtime._turn_completed is not None and runtime._turn_completed.is_set()

    # Yield so the _run coroutine resumes past sleep(0) and enters the trailing
    # work block in run_factory.
    await asyncio.wait_for(trailing_started.wait(), timeout=0.5)

    # wait_until_idle must return promptly, NOT wait for trailing work.
    await asyncio.wait_for(runtime.wait_until_idle(), timeout=0.5)
    assert runtime._task is not None and not runtime._task.done()  # trailing work still pending

    # Release the trailing work so the test can clean up.
    release_trailing.set()
    # Give the loop a chance to finalize.
    for _ in range(20):
        if runtime._task is None or runtime._task.done():
            break
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_new_turn_detaches_trailing_task_without_cancelling():
    runtime = SessionRuntime("sess-2")
    session = _fake_session("coding")

    release_trailing = asyncio.Event()
    trailing_completed = asyncio.Event()

    async def run_factory_first() -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "run_completed", "data": {"status": "completed"}}
        try:
            await release_trailing.wait()
        finally:
            trailing_completed.set()

    queue = runtime.subscribe()
    await runtime.start(session, run_factory_first)
    await _drain_subscriber(queue, "done")
    first_task = runtime._task
    assert first_task is not None and not first_task.done()

    async def run_factory_second() -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "status", "data": {"status": "thinking"}}
        yield {"type": "run_completed", "data": {"status": "completed"}}

    # Starting a new turn now should DETACH the first task (not cancel it).
    await runtime.start(session, run_factory_second)
    assert first_task in runtime._detached_tasks, "first task should be detached, not cancelled"
    assert not first_task.cancelled() and not first_task.done()

    # Drain the second turn's done.
    await _drain_subscriber(queue, "done")

    # The new task is a separate task.
    assert runtime._task is not first_task

    # Now release the first task's trailing work — it should complete cleanly.
    release_trailing.set()
    await asyncio.wait_for(trailing_completed.wait(), timeout=1.0)
    # Wait for done-callback bookkeeping.
    for _ in range(20):
        if first_task not in runtime._detached_tasks:
            break
        await asyncio.sleep(0.01)
    assert first_task not in runtime._detached_tasks
    assert not first_task.cancelled()


@pytest.mark.asyncio
async def test_explicit_cancel_still_cancels_after_done():
    runtime = SessionRuntime("sess-3")
    session = _fake_session("coding")

    cancel_observed = asyncio.Event()

    async def run_factory() -> AsyncIterator[Dict[str, Any]]:
        yield {"type": "run_completed", "data": {"status": "completed"}}
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancel_observed.set()
            raise

    queue = runtime.subscribe()
    await runtime.start(session, run_factory)
    await _drain_subscriber(queue, "done")
    task = runtime._task

    # Explicit cancel must cancel even after done was published.
    await runtime.cancel(session, broadcast=False)
    assert task is not None and task.done()
    assert cancel_observed.is_set() or task.cancelled()


@pytest.mark.asyncio
async def test_wait_until_idle_no_active_task():
    runtime = SessionRuntime("sess-4")
    # Should not raise / hang when nothing is running.
    await asyncio.wait_for(runtime.wait_until_idle(), timeout=0.1)
