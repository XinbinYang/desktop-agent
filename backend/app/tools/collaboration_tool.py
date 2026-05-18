from __future__ import annotations

from typing import Any, Dict, List

from app.collaboration.executor import (
    result_from_execute_events,
    run_consult_worker,
    run_execute_agent_events,
)
from app.collaboration.manager import add_task, complete_run, create_run, list_events, update_task
from app.collaboration.models import TaskPacket
from app.project_manager import ProjectManager
from app.tools.base import BaseTool, ToolResult


def _project_path() -> str:
    project = ProjectManager.get_current()
    return str(project.get("path") or "") if project else ""


def _event_payloads(run_id: str) -> List[Dict[str, Any]]:
    return [event.model_dump() for event in list_events(run_id)]


class ConsultCodingAgentTool(BaseTool):
    name = "consult_coding_agent"
    description = "Ask the Coding Agent for read-only technical diagnosis or implementation advice. Does not edit files."
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "Technical question or diagnostic goal."},
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
        context: Dict[str, Any] | None = None,
        acceptance_criteria: List[str] | None = None,
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        collab = create_run(
            session_id=session_id or "default",
            goal=goal,
            mode="consult",
            project_path=_project_path(),
        )
        packet = TaskPacket(
            goal=goal,
            mode="consult",
            user_intent=goal,
            context=context or {},
            acceptance_criteria=acceptance_criteria or ["Return a concise diagnosis and next step."],
            allowed_tools=["repo_map", "code_search", "file_outline", "file_read", "file_list", "file_search", "git_status", "git_diff"],
        )
        task = add_task(collab.run_id, packet)
        update_task(task.task_id, status="running")
        result, _worker_events = await run_consult_worker(packet, run_id=collab.run_id, task_id=task.task_id)
        update_task(task.task_id, status="completed" if result.status == "pass" else "failed", result=result)
        complete_run(collab.run_id, "completed" if result.status == "pass" else "failed", result.summary)
        return ToolResult(
            output=result.summary or result.details,
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
        },
        "required": ["goal"],
    }

    async def execute(
        self,
        goal: str,
        context: Dict[str, Any] | None = None,
        acceptance_criteria: List[str] | None = None,
        constraints: List[str] | None = None,
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        collab = create_run(
            session_id=session_id or "default",
            goal=goal,
            mode="execute",
            project_path=_project_path(),
        )
        packet = TaskPacket(
            goal=goal,
            mode="execute",
            user_intent=goal,
            context=context or {},
            acceptance_criteria=acceptance_criteria or ["Implementation satisfies the user goal.", "Verification evidence is reported."],
            constraints=constraints or ["Keep changes scoped to the requested task."],
        )
        task = add_task(collab.run_id, packet)
        update_task(task.task_id, status="running")
        events: List[Dict[str, Any]] = []
        async for event in run_execute_agent_events(packet, session_id=session_id or "default", run_id=collab.run_id):
            events.append(event)
        result = result_from_execute_events(events)
        update_task(task.task_id, status="completed" if result.status == "pass" else "failed", result=result)
        complete_run(collab.run_id, "completed" if result.status == "pass" else "failed", result.summary)
        return ToolResult(
            output=result.summary or result.details,
            metadata={
                "collaboration_run_id": collab.run_id,
                "collaboration_task_id": task.task_id,
                "collaboration_events": _event_payloads(collab.run_id),
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
        project = ProjectManager.get_current() or {}
        output = (
            f"Topic: {topic}\n\n"
            f"Project: {project.get('name', '')} {project.get('path', '')}\n\n"
            f"Shared user preferences:\n{prefs or '(none)'}\n\n"
            f"Cross-agent memory:\n{cross or '(none)'}"
        )
        return ToolResult(output=output)
