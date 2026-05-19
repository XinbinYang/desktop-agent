from __future__ import annotations

from typing import Any, AsyncGenerator, Dict, List, Tuple

from app.collaboration.models import ResultPacket, TaskPacket
from app.config import get_model_for_agent
from app.worker import WorkerSession


def _task_text(packet: TaskPacket) -> str:
    criteria = "\n".join(f"- {item}" for item in packet.acceptance_criteria if item)
    constraints = "\n".join(f"- {item}" for item in packet.constraints if item)
    parts = [
        "You are the Coding Agent working as a specialist for the Personal Agent.",
        "Return concise technical findings and end with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        "",
        f"Goal: {packet.goal}",
    ]
    if packet.user_intent:
        parts.extend(["", f"User intent: {packet.user_intent}"])
    if packet.product_intent:
        parts.extend(["", f"Product intent: {packet.product_intent}"])
    if constraints:
        parts.extend(["", "Constraints:", constraints])
    if criteria:
        parts.extend(["", "Acceptance criteria:", criteria])
    if packet.context:
        parts.extend(["", "Context:", str(packet.context)[:4000]])
    if packet.mode == "consult":
        parts.extend([
            "",
            "Mode: read-only consultation. Diagnose, inspect, and recommend. Do not edit files.",
        ])
    else:
        parts.extend([
            "",
            "Mode: execute. Make the smallest safe code change, verify it, review it, and report evidence.",
        ])
    return "\n".join(parts)


async def run_consult_worker(
    packet: TaskPacket,
    *,
    run_id: str,
    task_id: str,
) -> Tuple[ResultPacket, List[Dict[str, Any]]]:
    """Run a read-only Coding specialist using the architect worker profile."""
    model_id = get_model_for_agent("coding")
    worker = WorkerSession(
        worker_id=f"coding_consult_{task_id[-6:]}",
        task=_task_text(packet),
        profile_name="architect",
        model_id=model_id,
        run_id=run_id,
        parent_tool_call_id=task_id,
        agent_type="coding",
    )
    events: List[Dict[str, Any]] = []
    final = ""
    status = "pass"
    async for event in worker.run():
        events.append(event)
        if event.get("type") == "worker_done":
            data = event.get("data") or {}
            final = data.get("result", "")
            if data.get("status") not in ("completed", "max_iterations_reached"):
                status = "fail"
    if "ACCEPTANCE: FAIL" in final:
        status = "fail"
    return ResultPacket(status=status, summary=final[:4000], details=final), events


async def run_execute_agent_events(
    packet: TaskPacket,
    *,
    session_id: str,
    run_id: str,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Run a full Coding Agent session and yield its native events."""
    from app.agent import AgentSession
    from app.agents.manager import AgentManager

    model_id = get_model_for_agent("coding")
    coding_session = AgentSession(
        model_id=model_id,
        session_id=f"{session_id}_coding_delegate_{run_id[-6:]}",
        role_id=AgentManager.get_default_role("coding"),
        agent_type="coding",
    )
    # Keep delegated specialist sessions out of the user's visible session list.
    coding_session._save = lambda: None  # type: ignore[method-assign]
    async for event in coding_session.run(_task_text(packet), None, chat_mode="agent"):
        yield event


def result_from_execute_events(events: List[Dict[str, Any]]) -> ResultPacket:
    content = "".join(
        str((event.get("data") or {}).get("text") or "")
        for event in events
        if event.get("type") == "content"
    ).strip()
    run_completed = next((event for event in reversed(events) if event.get("type") == "run_completed"), None)
    completed_data = (run_completed or {}).get("data") or {}
    verification = completed_data.get("verification_passed")
    review = completed_data.get("review_passed")
    status = "pass"
    if completed_data.get("status") in {"failed", "cancelled", "max_iterations_reached"}:
        status = "fail"
    if verification is False or review is False:
        status = "fail"
    if "ACCEPTANCE: FAIL" in content:
        status = "fail"
    return ResultPacket(
        status=status,
        summary=content[:4000] or completed_data.get("summary", ""),
        details=content,
        verification_passed=verification if isinstance(verification, bool) else None,
        review_passed=review if isinstance(review, bool) else None,
    )
