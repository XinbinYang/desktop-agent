from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from app.collaboration.clarification import resolve_personal_clarification
from app.collaboration.executor import (
    record_delegated_child_event,
    result_from_execute_events,
    run_consult_worker,
    run_critic_loop_events,
    run_execute_agent_events,
    run_plan_then_execute_events,
    run_verify_only_events,
)
from app.coding_runs import effective_project_path
from app.collaboration.manager import add_task, complete_run, create_run, list_events, update_task
from app.collaboration.models import ResultPacket, TaskPacket
from app.collaboration.targeting import resolve_collaboration_target
from app.runtime_paths import runtime_file
from app.tools.base import BaseTool, ToolResult
from app.tools.worker_tool import emit_runtime_event

def _event_payloads(run_id: str) -> List[Dict[str, Any]]:
    return [event.model_dump() for event in list_events(run_id)]


def _collaboration_ws_event(event: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(event.get("data") or {})
    collab_run_id = event.get("run_id") or data.get("run_id") or ""
    collab_task_id = event.get("task_id") or data.get("task_id") or ""
    if collab_run_id:
        data.setdefault("run_id", collab_run_id)
        data.setdefault("collaboration_run_id", collab_run_id)
    if collab_task_id:
        data.setdefault("task_id", collab_task_id)
        data.setdefault("collaboration_task_id", collab_task_id)
    data.setdefault("timestamp", event.get("timestamp") or time.time())
    return {"type": event.get("type", "collaboration_task_update"), "data": data}


def _publish_new_collaboration_events(run_id: str, emitted_count: int) -> tuple[int, bool]:
    events = _event_payloads(run_id)
    published = False
    for event in events[emitted_count:]:
        published = emit_runtime_event(_collaboration_ws_event(event)) or published
    return len(events), published


def _format_result_output(result: ResultPacket, *, run_id: str) -> str:
    lines = [
        f"Collaboration run: {run_id}",
        f"Status: {result.status}",
        "",
        result.summary or result.details or "(no summary)",
    ]
    if result.changed_files:
        lines.extend(["", "Changed files:", *[f"- {path}" for path in result.changed_files[:20]]])
    if result.tests_run:
        lines.extend(["", "Verification:", *[f"- {item}" for item in result.tests_run[:10]]])
    elif result.verification_passed is False:
        lines.extend(["", "Verification:", "- Required verification did not pass."])
    if result.review_passed is not None:
        lines.extend(["", "Review:", f"- {'Passed' if result.review_passed else 'Failed or blocked'}"])
    if result.artifacts:
        lines.extend([
            "",
            "Artifacts:",
            *[
                f"- {artifact.title or artifact.id}: {artifact.path or artifact.url or artifact.id}"
                for artifact in result.artifacts[:10]
            ],
        ])
    if result.blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in result.blockers[:10]]])
    return "\n".join(lines).strip()


class ConsultCodingAgentTool(BaseTool):
    name = "consult_coding_agent"
    description = "Ask the Coding Agent for read-only technical diagnosis or implementation advice. Does not edit files."
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Technical question or diagnostic goal."},
            "project_path": {
                "type": "string",
                "description": "Optional absolute local project directory for this Coding Agent task.",
            },
            "context": {"type": "object", "description": "Optional structured context from the Personal Agent."},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Criteria for a useful answer.",
            },
        },
        "required": ["goal"],
    }

    async def execute(
        self,
        goal: str,
        project_path: str = "",
        context: Dict[str, Any] | None = None,
        acceptance_criteria: List[str] | None = None,
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        target = resolve_collaboration_target(
            project_path=project_path,
            context=context,
            user_message=goal,
            allow_global=True,
        )
        if not target.ok:
            return ToolResult(error=target.error)
        resolved_project_path = target.project_path
        collab = create_run(
            session_id=session_id or "default",
            goal=goal,
            mode="consult",
            project_path=resolved_project_path,
        )
        packet = TaskPacket(
            goal=goal,
            mode="consult",
            user_intent=goal,
            context={**(context or {}), "project_path": resolved_project_path, "target_source": target.source},
            acceptance_criteria=acceptance_criteria or ["Return a concise diagnosis and next step."],
            allowed_tools=[
                "repo_map", "code_search", "file_outline",
                "file_read", "file_list", "file_search",
                "git_status", "git_diff",
                "web_search", "web_fetch",
            ],
        )
        task = add_task(collab.run_id, packet)
        update_task(task.task_id, status="running")
        result, worker_events = await run_consult_worker(
            packet,
            run_id=collab.run_id,
            task_id=task.task_id,
            project_path=resolved_project_path,
        )
        for event in worker_events:
            record_delegated_child_event(collab.run_id, task.task_id, event)
        update_task(task.task_id, status="completed" if result.status == "pass" else "failed", result=result)
        complete_run(collab.run_id, "completed" if result.status == "pass" else "failed", result.summary)
        return ToolResult(
            output=_format_result_output(result, run_id=collab.run_id),
            metadata={
                "collaboration_run_id": collab.run_id,
                "collaboration_task_id": task.task_id,
                "collaboration_events": _event_payloads(collab.run_id),
            },
        )


class DelegateToCodingAgentTool(BaseTool):
    name = "delegate_to_coding_agent"
    description = "Delegate an executable coding task to the Coding Agent. Uses the Coding Agent's engineering workflow and worktree policy."
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Engineering task to execute."},
            "project_path": {
                "type": "string",
                "description": "Optional absolute local project directory for this Coding Agent task.",
            },
            "context": {"type": "object", "description": "Optional structured task context."},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Evidence required before the task is accepted.",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Boundaries and forbidden actions.",
            },
            "mode": {
                "type": "string",
                "enum": ["execute", "plan_then_execute", "critic", "verify_only"],
                "description": "Execution workflow. Defaults to execute.",
            },
        },
        "required": ["goal"],
    }

    async def execute(
        self,
        goal: str,
        project_path: str = "",
        context: Dict[str, Any] | None = None,
        acceptance_criteria: List[str] | None = None,
        constraints: List[str] | None = None,
        mode: str = "execute",
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
        session_model_id: str = "",
    ) -> ToolResult:
        if mode not in {"execute", "plan_then_execute", "critic", "verify_only"}:
            mode = "execute"
        target = resolve_collaboration_target(
            project_path=project_path,
            context=context,
            user_message=goal,
            allow_global=True,
        )
        if not target.ok:
            return ToolResult(error=target.error)
        resolved_project_path = target.project_path
        collab = create_run(
            session_id=session_id or "default",
            goal=goal,
            mode=mode,
            project_path=resolved_project_path,
        )
        packet = TaskPacket(
            goal=goal,
            mode=mode,  # type: ignore[arg-type]
            user_intent=goal,
            context={**(context or {}), "project_path": resolved_project_path, "target_source": target.source},
            acceptance_criteria=acceptance_criteria or ["Implementation satisfies the user goal.", "Verification evidence is reported."],
            constraints=constraints or ["Keep changes scoped to the requested task."],
        )
        task = add_task(collab.run_id, packet)
        update_task(task.task_id, status="running")
        emitted = 0
        live_events_published = False
        emitted, published = _publish_new_collaboration_events(collab.run_id, emitted)
        live_events_published = live_events_published or published

        async def clarification_resolver(clarification: Dict[str, Any], active_packet: TaskPacket):
            return await resolve_personal_clarification(
                clarification,
                active_packet,
                model_id=session_model_id,
            )

        events: List[Dict[str, Any]] = []
        if mode == "plan_then_execute":
            iterator = run_plan_then_execute_events(
                packet,
                session_id=session_id or "default",
                run_id=collab.run_id,
                task_id=task.task_id,
                project_path=resolved_project_path,
                clarification_resolver=clarification_resolver,
            )
        elif mode == "critic":
            iterator = run_critic_loop_events(
                packet,
                session_id=session_id or "default",
                run_id=collab.run_id,
                task_id=task.task_id,
                project_path=resolved_project_path,
                clarification_resolver=clarification_resolver,
            )
        elif mode == "verify_only":
            iterator = run_verify_only_events(
                packet,
                run_id=collab.run_id,
                task_id=task.task_id,
                project_path=resolved_project_path,
            )
        else:
            iterator = run_execute_agent_events(
                packet,
                session_id=session_id or "default",
                run_id=collab.run_id,
                task_id=task.task_id,
                project_path=resolved_project_path,
                clarification_resolver=clarification_resolver,
            )
        async for event in iterator:
            events.append(event)
            record_delegated_child_event(collab.run_id, task.task_id, event)
            emitted, published = _publish_new_collaboration_events(collab.run_id, emitted)
            live_events_published = live_events_published or published
        result = result_from_execute_events(events)
        task_status = "completed" if result.status == "pass" else ("blocked" if result.status == "blocked" else "failed")
        update_task(task.task_id, status=task_status, result=result)
        complete_run(
            collab.run_id,
            "completed" if result.status == "pass" else "failed",
            result.summary,
            artifacts=result.artifacts,
        )
        emitted, published = _publish_new_collaboration_events(collab.run_id, emitted)
        live_events_published = live_events_published or published
        return ToolResult(
            output=_format_result_output(result, run_id=collab.run_id),
            metadata={
                "collaboration_run_id": collab.run_id,
                "collaboration_task_id": task.task_id,
                "collaboration_events": _event_payloads(collab.run_id),
                "collaboration_events_realtime": live_events_published,
            },
        )


class RequestPersonalContextTool(BaseTool):
    name = "request_personal_context"
    description = "Request a privacy-scoped summary of user preferences and project intent from the Personal Agent workspace."
    parameters = {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The context topic the Coding Agent needs."},
        },
        "required": ["topic"],
    }

    async def execute(self, topic: str) -> ToolResult:
        from app.agents.manager import AgentManager

        prefs = AgentManager.load_workspace_file("_shared", "user_preferences.md")[:3000]
        cross = AgentManager.load_workspace_file("_shared", "cross_agent_memory.md")[:3000]
        from app.project_manager import ProjectManager
        project = ProjectManager.project_info_for(effective_project_path(allow_global=False)) or {}
        output = (
            f"Topic: {topic}\n\n"
            f"Project: {project.get('name', '')} {project.get('path', '')}\n\n"
            f"Shared user preferences:\n{prefs or '(none)'}\n\n"
            f"Cross-agent memory:\n{cross or '(none)'}"
        )
        return ToolResult(output=output)


class RequestPersonalClarificationTool(BaseTool):
    name = "request_personal_clarification"
    description = (
        "Ask the Personal Agent for a mid-task decision when a delegated Coding Agent "
        "is blocked by product intent, user preference, or a non-obvious tradeoff. "
        "Use this instead of guessing on user-visible behavior or risky choices."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The concise question the Personal Agent should answer.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional concrete choices, with your recommended choice first when possible.",
            },
            "context": {
                "type": "string",
                "description": "Brief technical context and why this cannot be safely inferred.",
            },
            "recommendation": {
                "type": "string",
                "description": "Optional recommended answer and rationale.",
            },
        },
        "required": ["question"],
    }

    async def execute(
        self,
        question: str,
        options: List[str] | None = None,
        context: str = "",
        recommendation: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        clean_options = [str(item).strip() for item in (options or []) if str(item).strip()]
        request_id = f"clar_{uuid.uuid4().hex[:12]}"
        payload = {
            "request_id": request_id,
            "question": str(question or "").strip(),
            "options": clean_options[:8],
            "context": str(context or "").strip()[:4000],
            "recommendation": str(recommendation or "").strip()[:2000],
            "agent_run_id": run_id,
            "tool_call_id": tool_call_id,
            "created_at": time.time(),
        }
        lines = [
            "[WAITING_FOR_PERSONAL_CLARIFICATION]",
            f"request_id: {request_id}",
            f"question: {payload['question']}",
        ]
        if clean_options:
            lines.append("options:")
            lines.extend(f"- {item}" for item in clean_options[:8])
        if recommendation:
            lines.append(f"recommendation: {payload['recommendation']}")
        return ToolResult(
            output="\n".join(lines),
            metadata={"collaboration_clarification_request": payload},
        )


class CollabHistorySearchTool(BaseTool):
    name = "collab_history_search"
    description = (
        "Search past collaboration runs with the Coding Agent. "
        "Returns compact RecapSummaries of matching runs so Personal Agent can recall what was done."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Keywords to match against run goals and summaries.",
            },
            "last_n": {
                "type": "integer",
                "description": "Maximum number of runs to return (default 10).",
            },
            "status_filter": {
                "type": "string",
                "enum": ["completed", "failed", "cancelled", "any"],
                "description": "Filter by run status (default 'any').",
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        last_n: int = 10,
        status_filter: Optional[str] = None,
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        from app.collaboration.recap import recap_from_events

        db_path = runtime_file("data", "collaboration_runs.db")
        if not db_path.exists():
            return ToolResult(output="No collaboration history found.")

        try:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row

            sql = "SELECT * FROM collaboration_runs WHERE 1=1"
            params: list = []

            if status_filter and status_filter != "any":
                sql += " AND status = ?"
                params.append(status_filter)

            if query:
                sql += " AND (goal LIKE ? OR summary LIKE ?)"
                like = f"%{query}%"
                params.extend([like, like])

            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(max(1, min(last_n, 50)))

            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as exc:
            return ToolResult(error=f"Database error: {exc}")

        if not rows:
            return ToolResult(output=f"No collaboration runs found matching '{query}'.")

        parts: List[str] = []
        for row in rows:
            run_id_row = row["run_id"]
            goal = row["goal"] or ""
            status = row["status"]
            summary = row["summary"] or ""

            # Build a minimal recap without hitting the DB again (use stored summary)
            line = f"[{run_id_row}] {status.upper()} — {goal[:80]}"
            if summary:
                line += f"\n  摘要: {summary[:120]}"
            parts.append(line)

        output = f"找到 {len(parts)} 条协作记录（查询: '{query}'）:\n\n" + "\n\n".join(parts)
        return ToolResult(output=output)
