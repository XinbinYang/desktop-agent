"""Collaboration Event Bus — inject_directive / poll_directive for P3.

Allows the Personal Agent (or the user via frontend) to inject mid-run directives
into an active Coding Agent collaboration.

Usage::
    # Personal side
    from app.collaboration.bus import inject_directive
    await inject_directive(run_id, "Please focus on error handling first")

    # Coding side (in the worker loop, before each LLM call)
    from app.collaboration.bus import poll_directive
    directive = await poll_directive(run_id)
    if directive:
        # inject as high-priority system message
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

_log: Dict[str, asyncio.Queue] = {}
_clarification_answers: Dict[str, asyncio.Queue] = {}


def get_directive_queue(run_id: str) -> asyncio.Queue:
    """Return the per-run directive queue, creating it if absent."""
    if run_id not in _log:
        _log[run_id] = asyncio.Queue()
    return _log[run_id]


def get_clarification_answer_queue(run_id: str) -> asyncio.Queue:
    """Return the per-run clarification answer queue, creating it if absent."""
    if run_id not in _clarification_answers:
        _clarification_answers[run_id] = asyncio.Queue()
    return _clarification_answers[run_id]


async def inject_directive(run_id: str, directive: str) -> None:
    """Push a directive string into the run's queue."""
    q = get_directive_queue(run_id)
    await q.put(directive)


async def poll_directive(run_id: str) -> Optional[str]:
    """Non-blocking check — returns the next directive or None.

    Safe to call in any event loop iteration (e.g. before each LLM call).
    """
    q = get_directive_queue(run_id)
    try:
        return q.get_nowait()
    except asyncio.QueueEmpty:
        return None


async def submit_clarification_answer(
    run_id: str,
    answer: str,
    *,
    request_id: str = "",
    answered_by: str = "personal",
) -> Dict[str, Any]:
    """Submit an answer for a pending Coding Agent clarification request."""
    payload = {
        "run_id": run_id,
        "request_id": request_id,
        "answer": answer,
        "answered_by": answered_by,
        "timestamp": time.time(),
    }
    await get_clarification_answer_queue(run_id).put(payload)
    return payload


async def wait_for_clarification_answer(
    run_id: str,
    *,
    request_id: str = "",
    timeout: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Wait for a clarification answer for *run_id*.

    Answers are run-scoped. If request_id is supplied and an older answer for a
    different request arrives, keep waiting until timeout.
    """
    queue = get_clarification_answer_queue(run_id)
    deadline = None if timeout is None else time.monotonic() + max(0.1, timeout)
    while True:
        wait_timeout = None if deadline is None else max(0.1, deadline - time.monotonic())
        if deadline is not None and wait_timeout <= 0.1 and time.monotonic() >= deadline:
            return None
        try:
            payload = await asyncio.wait_for(queue.get(), timeout=wait_timeout)
        except asyncio.TimeoutError:
            return None
        if not request_id or not payload.get("request_id") or payload.get("request_id") == request_id:
            return payload


def clear_directives(run_id: str) -> None:
    """Drop all pending directives for a run (e.g. on completion)."""
    q = get_directive_queue(run_id)
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break


def clear_clarification_answers(run_id: str) -> None:
    """Drop all pending clarification answers for a run."""
    q = get_clarification_answer_queue(run_id)
    while not q.empty():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            break
