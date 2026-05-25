from __future__ import annotations

import copy
import json
import time
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional, Tuple

from app.collaboration.models import ArtifactRef, EvidenceEntry, ResultPacket, TaskPacket
from app.config import get_model_for_agent


COLLAB_PHASE_EVENT_TYPE = "collaboration_phase_update"


def _try_transition(run_id: str, new_phase: str, note: str = "") -> Optional[Dict[str, Any]]:
    """Attempt a state-machine transition for *run_id*.

    Returns a ``collaboration_phase_update`` event dict if the transition
    succeeded, or ``None`` if it was illegal (logged but not raised — the
    state machine is observational, not a critical-path gate).
    """
    from app.collaboration.state_machine import CollaborationStateMachine

    sm = CollaborationStateMachine(run_id)
    previous = sm.phase()
    try:
        sm.transition(new_phase, note)
    except ValueError as exc:
        logger = __import__("logging").getLogger("collab.state_machine")
        logger.warning("Phase transition skipped for %s: %s", run_id, exc)
        return None
    return {
        "type": COLLAB_PHASE_EVENT_TYPE,
        "data": {
            "run_id": run_id,
            "phase": new_phase,
            "previous_phase": previous,
            "note": note,
            "timestamp": time.time(),
        },
    }


# Read-only tool set for critic and verify_only modes
CRITIC_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "repo_map", "code_search", "file_outline", "file_read", "file_list",
    "file_search", "git_status", "git_diff", "run_review",
})

VERIFY_ONLY_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "verify_project", "run_tests", "git_diff", "git_status", "run_review",
    "file_read", "file_list", "shell_execute",
})

_FILE_MUTATION_TOOLS: frozenset[str] = frozenset({
    "file_write",
    "file_patch",
    "file_delete",
    "coding_file_write",
})

RELAYED_CHILD_EVENT_TYPES: frozenset[str] = frozenset({
    "run_created",
    "tool_call",
    "worker_tool_call",
    "todo_update",
    "verification_result",
    "review_finding",
    "artifact_ready",
    "file_edit",
    "error",
    "decision_required",
    "collab_directive_applied",
    "collaboration_clarification_request",
    "collaboration_clarification_answer",
    "collaboration_plan_auto_approved",
    "collab_critic_result",
    "run_completed",
})

_VERIFICATION_COMMAND_HINTS: tuple[str, ...] = (
    "pytest",
    "vitest",
    "npm test",
    "npm run test",
    "npm run build",
    "yarn test",
    "pnpm test",
    "cargo test",
    "go test",
    "verify_project",
    "run_tests",
)

_BLOCKING_REVIEW_SEVERITIES: frozenset[str] = frozenset({
    "blocker",
    "blocking",
    "critical",
    "high",
    "error",
})

ClarificationResolver = Callable[[Dict[str, Any], TaskPacket], Awaitable[Any]]


def record_delegated_child_event(run_id: str, task_id: str, event: Dict[str, Any]) -> None:
    """Persist important child-agent events into the collaboration journal."""
    event_type = str(event.get("type") or "")
    if event_type not in RELAYED_CHILD_EVENT_TYPES:
        return
    data = dict(event.get("data") or {})
    data["collaboration_run_id"] = run_id
    data["collaboration_task_id"] = task_id
    data.setdefault("run_id", run_id)
    data.setdefault("task_id", task_id)
    from app.collaboration.manager import record_event

    record_event(run_id, event_type, data, task_id)


def _resolution_get(resolution: Any, key: str, default: Any = None) -> Any:
    if isinstance(resolution, dict):
        return resolution.get(key, default)
    return getattr(resolution, key, default)


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
        try:
            context_text = json.dumps(packet.context, ensure_ascii=False, indent=2)
        except TypeError:
            context_text = str(packet.context)
        parts.extend(["", "Context:", context_text[:12000]])
    if packet.mode == "consult":
        parts.extend([
            "",
            "Mode: read-only consultation. Diagnose, inspect, and recommend. Do not edit files.",
        ])
    else:
        parts.extend([
            "",
            "Mode: execute. Make the smallest safe code change, verify it, review it, and report evidence.",
            "Delegated execution contract: this task is already approved by the Personal Agent. "
            "If you need to plan, you may call plan_write_draft, but do not wait for a human Build click; "
            "the collaboration runner will auto-approve that plan and resume execution immediately. "
            "Do not finish after only drafting a plan.",
        ])
    return "\n".join(parts)


async def run_consult_worker(
    packet: TaskPacket,
    *,
    run_id: str,
    task_id: str,
    project_path: str = "",
    read_only: bool = True,
) -> Tuple[ResultPacket, List[Dict[str, Any]]]:
    """Run a read-only Coding specialist via AgentSession(coding).

    Uses the unified AgentSession so that the Coding Agent identity is
    consistent across consult and execute paths. The ``read_only`` flag
    sets ``AgentSession.collaboration_read_only``, which surfaces a
    read-only constraint in the system prompt Active Collaboration segment.
    """
    from app.agent import AgentSession
    from app.agents.manager import AgentManager

    model_id = get_model_for_agent("coding")
    session = AgentSession(
        model_id=model_id,
        session_id=f"coding_consult_{task_id[-8:]}",
        role_id=AgentManager.get_default_role("coding"),
        agent_type="coding",
        project_path=project_path or None,
    )
    session.collaboration_run_id = run_id
    session.collaboration_task_id = task_id
    session.collaboration_mode = packet.mode
    session.collaboration_read_only = read_only
    # Persist but archive so the delegated session is referenceable without
    # polluting the user's session list.
    session.archived_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    events: List[Dict[str, Any]] = []
    final = ""
    status = "pass"

    token = None
    if project_path:
        try:
            from app.coding_runs import set_session_project
            token = set_session_project(project_path)
        except Exception:
            token = None
    try:
        async for event in session.run(_task_text(packet), None, chat_mode="agent"):
            event_data = dict(event.get("data") or {})
            event_data.setdefault("collaboration_run_id", run_id)
            if task_id:
                event_data.setdefault("collaboration_task_id", task_id)
            event = {**event, "data": event_data}
            events.append(event)
            if event.get("type") == "run_completed":
                data = event.get("data") or {}
                messages = data.get("messages") or []
                if messages:
                    # Last assistant message is the final answer
                    last_assistant = next(
                        (m for m in reversed(messages) if m.get("role") == "assistant"),
                        None,
                    )
                    if last_assistant:
                        final = "\n".join([c.get("text", "") for c in last_assistant.get("content", [])])
                if data.get("status", "completed") not in ("completed", "max_iterations_reached"):
                    status = "fail"
                break
    finally:
        if token is not None:
            try:
                from app.coding_runs import reset_session_project
                reset_session_project(token)
            except Exception:
                pass

    if "ACCEPTANCE: FAIL" in final:
        status = "fail"
    return ResultPacket(status=status, summary=final[:4000], details=final), events


async def run_execute_agent_events(
    packet: TaskPacket,
    *,
    session_id: str,
    run_id: str,
    task_id: str = "",
    project_path: str = "",
    auto_build_plans: bool = True,
    clarification_resolver: Optional[ClarificationResolver] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Run a full delegated Coding Agent session and yield its native events.

    Delegated tasks are already approved by Personal. If the child Coding Agent
    uses normal plan mode tooling and stops at ``awaiting_approval``, approve
    and resume it here so the collaboration run does not stall behind a Build
    button that Personal cannot click.
    """
    from app.agent import AgentSession
    from app.agent import PLAN_CONTINUE_MARKER
    from app.agents.manager import AgentManager

    model_id = get_model_for_agent("coding")
    coding_session = AgentSession(
        model_id=model_id,
        session_id=f"{session_id}_coding_delegate_{run_id[-6:]}",
        role_id=AgentManager.get_default_role("coding"),
        agent_type="coding",
        project_path=project_path or None,
    )
    coding_session.collaboration_run_id = run_id
    coding_session.collaboration_task_id = task_id
    coding_session.collaboration_mode = packet.mode
    # Persist the delegated session so resume and recap can reference it later.
    # Mark as archived so it does not pollute the default session list in the UI.
    coding_session.archived_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    next_input = _task_text(packet)

    # State machine: entry
    phase_event = _try_transition(run_id, "analyzing", f"Task mode={packet.mode}")
    if phase_event:
        yield phase_event

    auto_builds = 0
    max_auto_builds = 3
    while True:
        clarification_request: Optional[Dict[str, Any]] = None
        phase_seen = False
        async for event in coding_session.run(next_input, None, chat_mode="agent"):
            event_data = dict(event.get("data") or {})
            event_data.setdefault("collaboration_run_id", run_id)
            if task_id:
                event_data.setdefault("collaboration_task_id", task_id)
            event = {**event, "data": event_data}

            # Phase transitions driven by Coding Agent events
            event_type = event.get("type", "")
            if event_type == "plan_status" and not phase_seen:
                phase_seen = True
                pe = _try_transition(run_id, "planning", "Plan produced by Coding Agent")
                if pe:
                    yield pe
            elif event_type == "verification_result":
                pe = _try_transition(run_id, "verifying", "Verification result received")
                if pe:
                    yield pe
            elif event_type == "collab_critic_result":
                pe = _try_transition(run_id, "critiquing", "Critic review received")
                if pe:
                    yield pe

            if event.get("type") == "collaboration_clarification_request":
                pe = _try_transition(run_id, "awaiting_user", "Clarification requested by Coding Agent")
                if pe:
                    yield pe
                clarification_request = dict(event.get("data") or {})
                clarification_request.setdefault("run_id", run_id)
                clarification_request.setdefault("collaboration_run_id", run_id)
                if task_id:
                    clarification_request.setdefault("task_id", task_id)
                    clarification_request.setdefault("collaboration_task_id", task_id)
                continue
            if event.get("type") == "run_completed":
                status = (event.get("data") or {}).get("status", "")
                if status == "waiting_clarification":
                    continue
                final_phase = "completed" if status in ("completed", "max_iterations_reached") else "failed"
                pe = _try_transition(run_id, final_phase, f"Run finished: {status}")
                if pe:
                    yield pe
            yield event

        if clarification_request is not None:
            from app.collaboration.bus import wait_for_clarification_answer
            from app.collaboration.manager import update_task

            request_id = str(clarification_request.get("request_id") or "")
            if clarification_resolver is not None:
                try:
                    resolution = await clarification_resolver(clarification_request, packet)
                except Exception as exc:
                    resolution = {
                        "action": "ask_user",
                        "reason": f"Personal Agent arbitration failed: {exc}",
                        "confidence": 0.0,
                    }
                if str(_resolution_get(resolution, "action", "")).lower() == "answer":
                    answer_text = str(_resolution_get(resolution, "answer", "") or "").strip()
                    if answer_text:
                        answer = {
                            "run_id": run_id,
                            "request_id": request_id,
                            "answer": answer_text,
                            "answered_by": str(_resolution_get(resolution, "answered_by", "personal_auto") or "personal_auto"),
                            "reason": str(_resolution_get(resolution, "reason", "") or ""),
                            "confidence": float(_resolution_get(resolution, "confidence", 0.0) or 0.0),
                            "question": clarification_request.get("question") or "",
                            "timestamp": time.time(),
                        }
                        yield {"type": "collaboration_clarification_answer", "data": answer}
                        pe = _try_transition(run_id, "executing", "Clarification auto-resolved by Personal Agent")
                        if pe:
                            yield pe
                        next_input = (
                            "[Personal Agent clarification answer]\n"
                            f"Question: {clarification_request.get('question') or ''}\n"
                            f"Answer: {answer.get('answer') or ''}\n\n"
                            "Continue the delegated coding task using this answer. Do not ask the same question again "
                            "unless the answer is unusable."
                        )
                        continue

            update_task(task_id, status="waiting_clarification") if task_id else None
            yield {
                "type": "collaboration_clarification_request",
                "data": clarification_request,
            }
            yield {
                "type": "decision_required",
                "data": {
                    **clarification_request,
                    "kind": "clarification",
                    "reason": clarification_request.get("question") or "Clarification required.",
                },
            }
            timeout = max(30, int(getattr(packet.budget, "max_seconds", 600) or 600))
            answer = await wait_for_clarification_answer(
                run_id,
                request_id=request_id,
                timeout=timeout,
            )
            if answer is None:
                pe = _try_transition(run_id, "awaiting_user", "Clarification timed out — run blocked awaiting user")
                if pe:
                    yield pe
                yield {
                    "type": "decision_required",
                    "data": {
                        "run_id": run_id,
                        "kind": "clarification_timeout",
                        "reason": "Coding Agent clarification timed out. The run is blocked but can be resumed once the user answers.",
                        "question": clarification_request.get("question") or "Unresolved clarification",
                    },
                }
                yield {
                    "type": "run_completed",
                    "data": {
                        "status": "blocked",
                        "summary": "Timed out waiting for Personal Agent clarification. Run is salvageable.",
                        "clarification_request_id": request_id,
                    },
                }
                return
            update_task(task_id, status="running") if task_id else None
            yield {"type": "collaboration_clarification_answer", "data": answer}
            pe = _try_transition(run_id, "executing", "Clarification answered by Personal Agent")
            if pe:
                yield pe
            next_input = (
                "[Personal Agent clarification answer]\n"
                f"Question: {clarification_request.get('question') or ''}\n"
                f"Answer: {answer.get('answer') or ''}\n\n"
                "Continue the delegated coding task using this answer. Do not ask the same question again "
                "unless the answer is unusable."
            )
            continue

        if (
            not auto_build_plans
            or auto_builds >= max_auto_builds
            or coding_session.plan_state.phase != "awaiting_approval"
            or coding_session.plan_state.approved
        ):
            break

        if not coding_session.build_plan():
            yield {
                "type": "decision_required",
                "data": {
                    "run_id": run_id,
                    "reason": "Coding Agent produced a plan, but it could not be auto-approved.",
                    "phase": coding_session.plan_state.phase,
                },
            }
            break

        auto_builds += 1
        pe = _try_transition(run_id, "executing", "Plan auto-approved — proceeding to execution")
        if pe:
            yield pe
        yield {
            "type": "collaboration_plan_auto_approved",
            "data": {
                "run_id": run_id,
                "phase": coding_session.plan_state.phase,
                "auto_build_round": auto_builds,
                "todos": [t.model_dump() for t in coding_session.plan_state.todos],
            },
        }
        yield {
            "type": "plan_status",
            "data": coding_session.plan_event_payload(),
        }
        yield {
            "type": "todo_update",
            "data": {"todos": [t.model_dump() for t in coding_session.plan_state.todos]},
        }
        next_input = PLAN_CONTINUE_MARKER


# 工具名称到 evidence kind 的映射
_TOOL_EVIDENCE_KIND: Dict[str, str] = {
    "shell_execute": "command",
    "run_tests": "test",
    "verify_project": "test",
    "git_diff": "diff",
    "run_review": "review",
    "screenshot": "screenshot",
    "browser_screenshot": "screenshot",
}


def _extract_evidence(events: List[Dict[str, Any]]) -> List[EvidenceEntry]:
    """从事件流中提取结构化证据条目。"""
    entries: List[EvidenceEntry] = []
    for event in events:
        if event.get("type") not in {"tool_call", "worker_tool_call"}:
            continue
        data = event.get("data") or {}
        tool_name = data.get("name") or ""
        kind = _TOOL_EVIDENCE_KIND.get(tool_name)
        if not kind:
            continue
        args = data.get("args") or {}
        result_text = str(data.get("result") or "")
        command = ""
        exit_code = _infer_evidence_exit_code(tool_name, result_text)
        if tool_name == "shell_execute":
            command = args.get("command") or args.get("cmd") or ""
            # result 格式通常为 "exit_code: N\n<output>"
            first_line = result_text.split("\n", 1)[0]
            if first_line.startswith("exit_code:"):
                try:
                    exit_code = int(first_line.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    pass
        label = tool_name
        if command:
            label = command[:80]
        elif tool_name in ("run_tests", "verify_project"):
            label = args.get("path") or args.get("project_path") or tool_name
        entries.append(EvidenceEntry(
            kind=kind,  # type: ignore[arg-type]
            label=label,
            command=command,
            exit_code=exit_code,
            output_excerpt=result_text[:2048],
        ))
    for event in events:
        if event.get("type") != "collab_critic_result":
            continue
        data = event.get("data") or {}
        entries.append(EvidenceEntry(
            kind="review",
            label="critic review",
            output_excerpt=str(data.get("critic_summary") or "")[:2048],
        ))
    return entries


def _shell_command_looks_like_verification(command: str) -> bool:
    lowered = (command or "").lower()
    return any(hint in lowered for hint in _VERIFICATION_COMMAND_HINTS)


def _infer_evidence_exit_code(tool_name: str, result_text: str) -> Optional[int]:
    first_line = result_text.split("\n", 1)[0].strip()
    if first_line.startswith("exit_code:"):
        try:
            return int(first_line.split(":", 1)[1].strip())
        except (ValueError, IndexError):
            return None
    lowered = result_text.lower()
    if tool_name == "verify_project":
        if lowered.startswith("passed:"):
            return 0
        if lowered.startswith("failed:"):
            return 1
    if tool_name == "run_tests":
        failed_match = re_search_int(r"\b(\d+)\s+failed\b", lowered)
        error_match = re_search_int(r"\b(\d+)\s+errors?\b", lowered)
        if (failed_match and failed_match > 0) or (error_match and error_match > 0):
            return 1
        passed_match = re_search_int(r"\b(\d+)\s+passed\b", lowered)
        if passed_match and passed_match > 0:
            return 0
    return None


def re_search_int(pattern: str, text: str) -> Optional[int]:
    import re

    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _verification_output_looks_failed(entry: EvidenceEntry) -> bool:
    lowered = (entry.output_excerpt or "").lower()
    if "no tests found" in lowered:
        return True
    if re_search_int(r"\b(\d+)\s+failed\b", lowered):
        return True
    if re_search_int(r"\b(\d+)\s+errors?\b", lowered):
        return True
    failure_markers = ("[error]", "acceptance: fail", "failed:", "traceback", "command failed", "退出码")
    return any(marker in lowered for marker in failure_markers)


def _verification_output_looks_successful(entry: EvidenceEntry) -> bool:
    if entry.exit_code == 0:
        return True
    if entry.exit_code is not None:
        return False
    lowered = (entry.output_excerpt or "").lower()
    if _verification_output_looks_failed(entry):
        return False
    success_markers = (
        "acceptance: pass",
        "passed:",
        "all checks passed",
        "all tests passed",
        "build succeeded",
        "built in",
        "typecheck clean",
        "lint clean",
        "命令执行成功",
    )
    return any(marker in lowered for marker in success_markers) or bool(re_search_int(r"\b(\d+)\s+passed\b", lowered))


def _extract_changed_files(events: List[Dict[str, Any]]) -> List[str]:
    changed: list[str] = []
    seen: set[str] = set()

    def add(path: Any) -> None:
        text = str(path or "").strip()
        if text and text not in seen:
            seen.add(text)
            changed.append(text)

    for event in events:
        data = event.get("data") or {}
        if event.get("type") == "file_edit":
            add(data.get("path") or data.get("file_path") or data.get("file"))
        if event.get("type") not in {"tool_call", "worker_tool_call"}:
            continue
        name = str(data.get("name") or "")
        if name not in _FILE_MUTATION_TOOLS:
            continue
        args = data.get("args") or {}
        add(args.get("path") or args.get("file_path") or args.get("target"))
    return changed


def _extract_artifacts(events: List[Dict[str, Any]]) -> List[ArtifactRef]:
    artifacts: list[ArtifactRef] = []
    for event in events:
        data = event.get("data") or {}
        candidates: list[Any] = []
        if event.get("type") == "artifact_ready" and data.get("artifact"):
            candidates.append(data["artifact"])
        elif event.get("type") in {"tool_call", "worker_tool_call"}:
            candidates.extend(data.get("artifacts") or [])
        for artifact in candidates:
            try:
                artifacts.append(ArtifactRef.model_validate(artifact))
            except Exception:
                continue
    return artifacts


def _has_verification_evidence(
    events: List[Dict[str, Any]],
    evidence: List[EvidenceEntry],
    verification: Any,
) -> bool:
    for entry in evidence:
        if entry.kind == "test" and _verification_output_looks_successful(entry):
            return True
        if (
            entry.kind == "command"
            and _shell_command_looks_like_verification(entry.command)
            and (
                _verification_output_looks_successful(entry)
                or (entry.exit_code is None and not _verification_output_looks_failed(entry))
            )
        ):
            return True
    for event in events:
        if event.get("type") == "verification_result":
            data = event.get("data") or {}
            if data.get("passed") is True:
                return True
    return False


def _has_review_evidence(events: List[Dict[str, Any]], evidence: List[EvidenceEntry], review: Any) -> bool:
    if any(entry.kind == "review" for entry in evidence):
        return True
    for event in events:
        if event.get("type") == "collab_critic_result":
            data = event.get("data") or {}
            return data.get("critic_status") == "pass"
    return False


def _blocking_review_findings(events: List[Dict[str, Any]]) -> List[str]:
    blockers: list[str] = []
    for event in events:
        data = event.get("data") or {}
        if event.get("type") == "review_finding":
            severity = str(data.get("severity") or "").lower()
            if severity in _BLOCKING_REVIEW_SEVERITIES:
                message = str(data.get("message") or data.get("body") or data)
                blockers.append(message[:500])
        elif event.get("type") == "collab_critic_result":
            if data.get("critic_status") == "fail":
                summary = str(data.get("critic_summary") or "Critic review failed.")
                blockers.append(summary[:500])
    return blockers


async def run_plan_then_execute_events(
    packet: TaskPacket,
    *,
    session_id: str,
    run_id: str,
    task_id: str,
    project_path: str = "",
    clarification_resolver: Optional[ClarificationResolver] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Two-phase mode: consult to draft a plan, then execute it.

    Phase 1 — Consult: Coding Agent produces a structured plan and emits a
    ``collab_plan_draft`` event so the frontend can display it to the user.

    Phase 2 — Execute: proceeds automatically with the plan injected as
    ``prior_attempts`` context.  An explicit approval gate (P3 state machine)
    will be layered on top when CollaborationStateMachine is available.
    """
    # Phase 1: produce a plan via read-only consult
    pe = _try_transition(run_id, "analyzing", "plan_then_execute: entering analysis")
    if pe:
        yield pe
    plan_packet = copy.copy(packet)
    plan_packet = plan_packet.model_copy(update={
        "mode": "consult",
        "acceptance_criteria": [
            "Output a numbered implementation plan with file paths and steps.",
            "State key risks and assumptions.",
            "End with ACCEPTANCE: PASS.",
        ],
        "constraints": list(packet.constraints) + [
            "Read-only planning pass. Do not edit any files.",
        ],
    })
    plan_result, plan_events = await run_consult_worker(
        plan_packet, run_id=run_id, task_id=task_id, project_path=project_path
    )
    for event in plan_events:
        yield event

    pe = _try_transition(run_id, "planning", "Plan draft produced")
    if pe:
        yield pe

    # Emit a structured plan-draft event for the frontend
    yield {
        "type": "collab_plan_draft",
        "data": {
            "run_id": run_id,
            "plan_text": plan_result.summary or plan_result.details,
            "status": plan_result.status,
        },
    }

    if plan_result.status == "fail":
        pe = _try_transition(run_id, "failed", "Planning phase failed")
        if pe:
            yield pe
        yield {
            "type": "run_completed",
            "data": {"status": "failed", "summary": "Planning phase failed; aborting execution."},
        }
        return

    # Phase 2: execute with the plan injected as prior context
    pe = _try_transition(run_id, "executing", "plan_then_execute: starting execution phase")
    if pe:
        yield pe
    exec_packet = packet.model_copy(update={
        "mode": "execute",
        "prior_attempts": list(packet.prior_attempts) + [
            f"Planning phase output:\n{(plan_result.summary or plan_result.details)[:2000]}"
        ],
    })
    async for event in run_execute_agent_events(
        exec_packet,
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
        project_path=project_path,
        clarification_resolver=clarification_resolver,
    ):
        yield event


async def run_critic_loop_events(
    packet: TaskPacket,
    *,
    session_id: str,
    run_id: str,
    task_id: str,
    project_path: str = "",
    clarification_resolver: Optional[ClarificationResolver] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute first, then run an independent read-only critic pass.

    The critic uses a second isolated Coding Agent instance with only read-only
    tools, so it cannot accidentally modify files.  If the critic finds blocking
    issues the final ResultPacket status becomes "blocked".
    """
    # Phase 1: execute
    execute_events: List[Dict[str, Any]] = []
    async for event in run_execute_agent_events(
        packet,
        session_id=session_id,
        run_id=run_id,
        task_id=task_id,
        project_path=project_path,
        clarification_resolver=clarification_resolver,
    ):
        execute_events.append(event)
        yield event

    # The independent critic pass below is the review gate for this mode, so
    # don't fail the pre-critic execution only because review evidence is not
    # present yet.
    execute_result = result_from_execute_events(execute_events, require_review=False)
    if execute_result.status == "fail":
        # Execution already failed; skip critic
        return

    # Phase 2: critic — independent read-only review of the diff
    pe = _try_transition(run_id, "critiquing", "Critic loop: starting independent review pass")
    if pe:
        yield pe
    critic_goal = (
        f"Independently review the code changes just made for goal: {packet.goal!r}.\n"
        "Read the git diff, check test results, inspect changed files.\n"
        "Report: any blocking quality/security/correctness issues, advisory findings, "
        "and overall verdict.\n"
        "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL."
    )
    critic_packet = TaskPacket(
        goal=critic_goal,
        mode="consult",
        user_intent="Independent code review",
        constraints=["Read-only. Do not edit any files."],
        acceptance_criteria=["Report blocking issues.", "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL."],
        allowed_tools=list(CRITIC_ALLOWED_TOOLS),
        context={"original_goal": packet.goal, "project_path": project_path},
    )
    critic_result, critic_events = await run_consult_worker(
        critic_packet, run_id=run_id, task_id=f"{task_id}_critic", project_path=project_path
    )
    for event in critic_events:
        yield event

    # Yield a structured critic-result event
    yield {
        "type": "collab_critic_result",
        "data": {
            "run_id": run_id,
            "critic_status": critic_result.status,
            "critic_summary": critic_result.summary,
        },
    }

    critic_text = critic_result.summary + critic_result.details
    critic_passed = critic_result.status == "pass" and "ACCEPTANCE: FAIL" not in critic_text
    yield {
        "type": "run_completed",
        "data": {
            "status": "completed" if critic_passed else "failed",
            "summary": (
                f"Critic review passed: {critic_result.summary[:500]}"
                if critic_passed
                else f"Critic found blocking issues: {critic_result.summary[:500]}"
            ),
            "verification_passed": execute_result.verification_passed,
            "review_passed": critic_passed,
        },
    }


async def run_verify_only_events(
    packet: TaskPacket,
    *,
    run_id: str,
    task_id: str,
    project_path: str = "",
) -> AsyncGenerator[Dict[str, Any], None]:
    """Verify-only mode: run tests/build/review without writing any code."""
    pe = _try_transition(run_id, "analyzing", "verify_only: starting verification check")
    if pe:
        yield pe
    pe = _try_transition(run_id, "verifying", "verify_only: running verification tools")
    if pe:
        yield pe
    verify_packet = packet.model_copy(update={
        "mode": "consult",
        "allowed_tools": list(VERIFY_ONLY_ALLOWED_TOOLS),
        "constraints": list(packet.constraints) + [
            "Verification only. Do not edit any files.",
            "Run verify_project, run_tests, and/or git_diff to check the current state.",
        ],
        "acceptance_criteria": list(packet.acceptance_criteria) + [
            "Report pass/fail status with evidence.",
            "End with ACCEPTANCE: PASS or ACCEPTANCE: FAIL.",
        ],
    })
    result, events = await run_consult_worker(
        verify_packet, run_id=run_id, task_id=task_id, project_path=project_path
    )
    for event in events:
        yield event
    verification_ok = _has_verification_evidence(events, _extract_evidence(events), None)
    final_status = "completed" if result.status == "pass" and verification_ok else "failed"
    pe = _try_transition(run_id, final_status, f"Verification-only finished: {final_status}")
    if pe:
        yield pe
    yield {
        "type": "content",
        "data": {"text": result.summary or result.details},
    }
    yield {
        "type": "run_completed",
        "data": {
            "status": final_status,
            "summary": result.summary or result.details,
            "verification_passed": verification_ok,
            "review_passed": None,
        },
    }


def result_from_execute_events(
    events: List[Dict[str, Any]],
    *,
    require_verification: Optional[bool] = None,
    require_review: Optional[bool] = None,
) -> ResultPacket:
    if require_verification is None or require_review is None:
        try:
            from app.config import load_config
            coding_cfg = load_config().coding_agent
            if require_verification is None:
                require_verification = bool(getattr(coding_cfg, "require_verification", True))
            if require_review is None:
                require_review = bool(getattr(coding_cfg, "require_review", True))
        except Exception:
            require_verification = True if require_verification is None else require_verification
            require_review = True if require_review is None else require_review

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
    blockers: list[str] = []
    evidence = _extract_evidence(events)
    changed_files = _extract_changed_files(events)
    artifacts = _extract_artifacts(events)
    review_blockers = _blocking_review_findings(events)
    tests_run = [
        (entry.command or entry.label)
        for entry in evidence
        if entry.kind == "test" or (entry.kind == "command" and _shell_command_looks_like_verification(entry.command))
    ]

    if not events:
        status = "fail"
        blockers.append("No events were produced by the delegated Coding Agent.")
    if not run_completed:
        status = "fail"
        blockers.append("Delegated Coding Agent did not emit a run_completed event.")
    latest_plan_phase = next(
        (
            (event.get("data") or {}).get("phase")
            for event in reversed(events)
            if event.get("type") == "plan_status"
        ),
        "",
    )
    if latest_plan_phase == "awaiting_approval":
        status = "fail"
        blockers.append("Delegated Coding Agent stopped at awaiting_approval instead of executing.")
    if completed_data.get("status") in {"failed", "cancelled", "max_iterations_reached"}:
        status = "fail"
    if verification is False or review is False:
        status = "fail"
    if "ACCEPTANCE: FAIL" in content:
        status = "fail"
    if review_blockers:
        if status == "pass":
            status = "blocked"
        blockers.extend(review_blockers)
    summary_text = content[:4000] or completed_data.get("summary", "")
    if not str(summary_text or "").strip():
        status = "fail"
        blockers.append("Delegated Coding Agent did not provide a result summary.")
    verification_ok = _has_verification_evidence(events, evidence, verification)
    review_ok = _has_review_evidence(events, evidence, review)
    if require_verification and not verification_ok:
        status = "fail"
        blockers.append("Verification evidence is required but was not observed.")
    if require_review and changed_files and not review_ok:
        status = "fail"
        blockers.append("Review evidence is required for file changes but was not observed.")

    # Quality gate: evidence minimum
    quality_config: dict = {}
    try:
        from app.config import load_config
        coding_cfg = load_config().coding_agent
        quality_config = dict(getattr(coding_cfg, "quality_gate", {}) or {})
    except Exception:
        pass
    evidence_min = int(quality_config.get("evidence_min_count") or 2)
    forbid_no_evidence = quality_config.get("forbid_acceptance_without_evidence", True)
    forbid_silent_skip = quality_config.get("forbid_silent_test_skip", True)

    if forbid_no_evidence and not evidence:
        status = "fail"
        blockers.append("No evidence entries were produced by the Coding Agent. At least one command or test output is required.")
    elif changed_files and len(evidence) < evidence_min and evidence_min > 1:
        # Evidence minimum only enforced when files were actually changed
        blockers.append(
            f"Evidence count ({len(evidence)}) is below minimum ({evidence_min}). "
            "The result may be incomplete."
        )
        if status == "pass":
            status = "blocked"

    if forbid_silent_skip and not changed_files and not verification_ok:
        if any("no tests" in (e.command or "").lower() or "0 test" in (e.output_excerpt or "").lower() for e in evidence):
            status = "fail"
            blockers.append(
                "Coding Agent reported zero tests but made no file changes. "
                "This appears to be a silent skip — the task was not actually attempted."
            )

    return ResultPacket(
        status=status,
        summary=summary_text,
        details=content,
        changed_files=changed_files,
        tests_run=tests_run,
        verification_passed=verification_ok if require_verification else (verification if isinstance(verification, bool) else None),
        review_passed=review_ok if (require_review and changed_files) else (review if isinstance(review, bool) else None),
        blockers=blockers,
        artifacts=artifacts,
        evidence=evidence,
    )
