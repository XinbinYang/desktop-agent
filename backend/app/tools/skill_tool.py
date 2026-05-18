from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.skill_authoring import (
    SkillAuthoringError,
    archive_skill,
    list_drafts,
    list_published_entries,
    publish_draft,
    read_skill,
    save_draft,
    validate_skill,
)
from app.skills import SkillManager
from app.tools.base import BaseTool, ToolResult


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


class SkillDraftSaveTool(BaseTool):
    name = "skill_draft_save"
    description = (
        "Create a draft Agent Skill from a reusable user workflow. Use this only after understanding "
        "the user's intended triggers and instructions. Drafts are not active until validated and published."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Lowercase/hyphen skill name; will be normalized if needed."},
            "description": {"type": "string", "description": "What the skill does and when to use it."},
            "body": {"type": "string", "description": "Markdown instructions for SKILL.md body."},
            "scopes": {
                "type": "array",
                "items": {"type": "string", "enum": ["personal", "coding"]},
                "description": "Agent scopes that may use this skill. Defaults to personal.",
            },
            "resources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "references/, assets/, or scripts/ relative path."},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                "description": "Optional bundled resources. Scripts make the draft high risk and require explicit publish confirmation.",
            },
            "compatibility": {"type": "string", "description": "Optional Agent Skills compatibility note."},
            "allowed_tools": {"type": "string", "description": "Optional standard allowed-tools declaration; does not bypass guardrails."},
        },
        "required": ["name", "description", "body"],
    }

    async def execute(
        self,
        name: str,
        description: str,
        body: str,
        scopes: Optional[List[str]] = None,
        resources: Optional[List[Dict[str, Any]]] = None,
        compatibility: str = "",
        allowed_tools: str = "",
    ) -> ToolResult:
        try:
            draft = save_draft(
                name=name,
                description=description,
                body=body,
                scopes=scopes,
                resources=resources,
                compatibility=compatibility,
                allowed_tools=allowed_tools,
                created_from="agent_tool",
            )
        except SkillAuthoringError as exc:
            return ToolResult(error=str(exc))
        output = (
            f"Skill draft saved: {draft['name']} (draft_id: {draft['draft_id']}). "
            "Review the validation result, then publish only after the user confirms."
        )
        return ToolResult(output=output + "\n\n" + _json(draft), metadata={"skill_draft": draft})


class SkillValidateTool(BaseTool):
    name = "skill_validate"
    description = "Validate a draft or published user Skill before publishing or after editing."
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Draft id, user:skill-name, or skill path."},
        },
        "required": ["id"],
    }

    async def execute(self, id: str) -> ToolResult:
        try:
            validation = validate_skill(id)
        except SkillAuthoringError as exc:
            return ToolResult(error=str(exc))
        status = "passed" if validation.get("passed") else "needs review"
        return ToolResult(output=f"Skill validation {status}.\n\n{_json(validation)}", metadata={"skill_validation": validation})


class SkillPublishTool(BaseTool):
    name = "skill_publish"
    description = (
        "Publish a validated Skill draft after explicit user confirmation. Do not call this merely because "
        "a draft validates; the user must approve publishing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "enable_for": {
                "type": "array",
                "items": {"type": "string", "enum": ["personal", "coding"]},
                "description": "Agents to enable immediately. Defaults to personal.",
            },
            "user_confirmed": {
                "type": "boolean",
                "description": "Must be true only when the user explicitly asked to publish/enable this draft.",
            },
            "allow_risky": {
                "type": "boolean",
                "description": "Set true only after explicit high-risk confirmation for scripts or risky findings.",
                "default": False,
            },
        },
        "required": ["draft_id", "user_confirmed"],
    }

    async def execute(
        self,
        draft_id: str,
        user_confirmed: bool,
        enable_for: Optional[List[str]] = None,
        allow_risky: bool = False,
    ) -> ToolResult:
        if not user_confirmed:
            return ToolResult(error="User confirmation is required before publishing a skill draft.")
        try:
            entry = publish_draft(draft_id, enable_for=enable_for, allow_risky=allow_risky)
        except SkillAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=f"Skill published: {entry['skill_id']}\n\n{_json(entry)}", metadata={"skill_published": entry})


class SkillListTool(BaseTool):
    name = "skill_list"
    description = "List available Agent Skills, plus user-created Skill drafts and published user Skills."
    parameters = {
        "type": "object",
        "properties": {
            "include_archived": {"type": "boolean", "default": False},
        },
    }

    async def execute(self, include_archived: bool = False) -> ToolResult:
        data = {
            "available": SkillManager.list_skill_catalog()["skills"],
            "drafts": list_drafts(),
            "published": list(list_published_entries(include_archived=include_archived).values()),
        }
        return ToolResult(output=_json(data))


class SkillReadTool(BaseTool):
    name = "skill_read"
    description = "Read an Agent Skill by id, including bundled, personal, user-created, or draft Skills."
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Skill id, draft id, user:skill-name, or personal:skill-name."},
        },
        "required": ["id"],
    }

    async def execute(self, id: str) -> ToolResult:
        try:
            data = read_skill(id)
        except SkillAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=_json(data))


class SkillArchiveTool(BaseTool):
    name = "skill_archive"
    description = "Archive a published user Skill so it no longer matches future turns."
    parameters = {
        "type": "object",
        "properties": {
            "skill_id": {"type": "string", "description": "user:skill-name or skill-name."},
        },
        "required": ["skill_id"],
    }

    async def execute(self, skill_id: str) -> ToolResult:
        try:
            entry = archive_skill(skill_id)
        except SkillAuthoringError as exc:
            return ToolResult(error=str(exc))
        return ToolResult(output=f"Skill archived: {entry['skill_id']}\n\n{_json(entry)}", metadata={"skill_archived": entry})
