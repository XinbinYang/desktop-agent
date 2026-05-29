from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from app.agents.specialists import (
    SpecialistAuthoringError,
    archive_specialist,
    list_specialists,
    publish_draft,
    read_specialist,
    save_draft,
    validate_specialist,
)
from app.config import get_model_for_agent
from app.tools.base import BaseTool, ToolResult


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


class SpecialistAgentDraftSaveTool(BaseTool):
    name = "specialist_agent_draft_save"
    description = (
        "Create an inert draft for a persistent Specialist Agent when the user asks for a durable sub-agent "
        "with its own identity, routing triggers, tools, model, or reusable specialty."
    )
    parameters = {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Lowercase specialist slug, e.g. stock-long-short."},
            "display_name": {"type": "string", "description": "User-facing specialist name."},
            "description": {"type": "string", "description": "What the specialist is for and when to use it."},
            "instructions": {"type": "string", "description": "Persistent specialist operating instructions."},
            "trigger_examples": {"type": "array", "items": {"type": "string"}},
            "routing_keywords": {"type": "array", "items": {"type": "string"}},
            "auto_delegate": {"type": "string", "enum": ["off", "suggest", "auto"], "default": "suggest"},
            "base_kind": {"type": "string", "enum": ["advisory", "coding", "desktop"], "default": "advisory"},
            "allowed_tools": {"type": "array", "items": {"type": "string"}},
            "skill_ids": {"type": "array", "items": {"type": "string"}},
            "model_id": {"type": "string"},
            "thinking_intensity": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
        },
        "required": ["display_name", "description", "instructions"],
    }

    async def execute(
        self,
        display_name: str,
        description: str,
        instructions: str,
        slug: str = "",
        trigger_examples: List[str] | None = None,
        routing_keywords: List[str] | None = None,
        auto_delegate: str = "suggest",
        base_kind: str = "advisory",
        allowed_tools: List[str] | None = None,
        skill_ids: List[str] | None = None,
        model_id: str = "",
        thinking_intensity: str = "medium",
    ) -> ToolResult:
        try:
            draft = save_draft(
                slug=slug,
                display_name=display_name,
                description=description,
                instructions=instructions,
                trigger_examples=trigger_examples or [],
                routing_keywords=routing_keywords or [],
                auto_delegate=auto_delegate,
                base_kind=base_kind,
                allowed_tools=allowed_tools or [],
                skill_ids=skill_ids or [],
                model_id=model_id,
                thinking_intensity=thinking_intensity,
                created_from="tool",
            )
        except SpecialistAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(
            output=f"Specialist Agent draft saved: {draft['draft_id']}\n\n{_json(draft)}",
            metadata={"specialist_agent_draft": draft},
        )


class SpecialistAgentValidateTool(BaseTool):
    name = "specialist_agent_validate"
    description = "Validate a Specialist Agent draft or published specialist before publishing or editing it."
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Draft id, slug, agent_type, or specialist path."}},
        "required": ["id"],
    }

    async def execute(self, id: str) -> ToolResult:
        try:
            validation = validate_specialist(id)
        except SpecialistAuthoringError as exc:
            return ToolResult(error=str(exc))
        status = "passed" if validation.get("passed") else "failed"
        return ToolResult(output=f"Specialist Agent validation {status}.\n\n{_json(validation)}", metadata={"specialist_validation": validation})


class SpecialistAgentPublishTool(BaseTool):
    name = "specialist_agent_publish"
    description = "Publish a validated Specialist Agent draft. Requires explicit user confirmation."
    parameters = {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "confirm": {"type": "boolean", "description": "True only after the user explicitly confirms publishing."},
            "allow_risky": {"type": "boolean", "description": "True only after explicit high-risk confirmation."},
        },
        "required": ["draft_id", "confirm"],
    }

    async def execute(self, draft_id: str, confirm: bool = False, allow_risky: bool = False) -> ToolResult:
        if not confirm:
            return ToolResult(error="User confirmation is required before publishing a Specialist Agent draft.")
        try:
            specialist = publish_draft(draft_id, allow_risky=allow_risky)
        except SpecialistAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=f"Specialist Agent published: {specialist['agent_type']}\n\n{_json(specialist)}", metadata={"specialist_published": specialist})


class SpecialistAgentListTool(BaseTool):
    name = "specialist_agent_list"
    description = "List published Specialist Agents."
    parameters = {"type": "object", "properties": {"include_archived": {"type": "boolean", "default": False}}}

    async def execute(self, include_archived: bool = False) -> ToolResult:
        return ToolResult(output=_json({"specialists": list_specialists(include_archived=include_archived)}))


class SpecialistAgentReadTool(BaseTool):
    name = "specialist_agent_read"
    description = "Read a Specialist Agent by slug or specialist:<slug> agent type."
    parameters = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}

    async def execute(self, id: str) -> ToolResult:
        try:
            specialist = read_specialist(id)
        except SpecialistAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=_json(specialist), metadata={"specialist": specialist})


class SpecialistAgentArchiveTool(BaseTool):
    name = "specialist_agent_archive"
    description = "Archive a published Specialist Agent by slug or specialist:<slug> agent type."
    parameters = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}

    async def execute(self, id: str) -> ToolResult:
        try:
            archived = archive_specialist(id)
        except SpecialistAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=f"Specialist Agent archived: {archived['agent_type']}\n\n{_json(archived)}", metadata={"specialist_archived": archived})


class DelegateToSpecialistAgentTool(BaseTool):
    name = "delegate_to_specialist_agent"
    description = "Delegate a task to a published Specialist Agent and return its result to Personal Agent."
    parameters = {
        "type": "object",
        "properties": {
            "agent_type": {"type": "string", "description": "specialist:<slug> or slug."},
            "goal": {"type": "string", "description": "Task for the Specialist Agent."},
            "context": {"type": "object"},
            "project_path": {"type": "string", "description": "Optional project path for coding specialists."},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["agent_type", "goal"],
    }

    async def execute(
        self,
        agent_type: str,
        goal: str,
        context: Dict[str, Any] | None = None,
        project_path: str = "",
        acceptance_criteria: List[str] | None = None,
        session_id: str = "",
    ) -> ToolResult:
        from app.agent import AgentSession
        from app.agents.manager import AgentManager
        from app.agents.specialists import AGENT_TYPE_PREFIX, SpecialistRegistry, normalize_slug

        resolved_agent_type = agent_type if agent_type.startswith(AGENT_TYPE_PREFIX) else f"{AGENT_TYPE_PREFIX}{normalize_slug(agent_type)}"
        spec = SpecialistRegistry.get(resolved_agent_type)
        if not spec:
            return ToolResult(error=f"Specialist Agent not found: {agent_type}")

        task_parts = [
            "You are running as a Specialist Agent delegated by Personal Agent.",
            "Report back concisely; Personal Agent owns the final user-facing reply.",
            "",
            f"Goal: {goal}",
        ]
        if acceptance_criteria:
            task_parts.extend(["", "Acceptance criteria:", "\n".join(f"- {item}" for item in acceptance_criteria)])
        if context:
            task_parts.extend(["", "Context:", json.dumps(context, ensure_ascii=False, indent=2)[:8000]])
        task_parts.extend(["", "End with SPECIALIST_ACCEPTANCE: PASS or SPECIALIST_ACCEPTANCE: FAIL."])

        child = AgentSession(
            model_id=get_model_for_agent(resolved_agent_type),
            session_id=f"{session_id or 'personal'}_specialist_{spec['slug']}_{int(time.time() * 1000)}",
            role_id=AgentManager.get_default_role(resolved_agent_type),
            agent_type=resolved_agent_type,
            project_path=project_path or None,
        )
        child.archived_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        final = ""
        async for event in child.run("\n".join(task_parts), None, chat_mode="agent"):
            if event.get("type") == "run_completed":
                data = event.get("data") or {}
                messages = data.get("messages") or []
                last = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
                if last:
                    final = "\n".join(part.get("text", "") for part in last.get("content", []))
                break
        if "SPECIALIST_ACCEPTANCE: FAIL" in final:
            return ToolResult(output=final, error=final, metadata={"specialist_agent_type": resolved_agent_type})
        return ToolResult(output=final or "Specialist Agent returned no final content.", metadata={"specialist_agent_type": resolved_agent_type})
