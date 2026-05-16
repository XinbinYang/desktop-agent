"""Plan-mode tools: plan_ask_questions and plan_write_draft.

These tools are only offered during the pre-approval planning phases.
They are *pure* — they validate input, return structured payloads in
metadata, and let the AgentSession run loop apply side effects
(write plan_state, persist files, emit WS events).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolResult


# ── plan_ask_questions ─────────────────────────────────────────────

_ASK_QUESTIONS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "description": "Clarifying questions the user must answer.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Stable identifier, e.g. 'scope' or 'target_platform'.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The question text. In the user's language.",
                    },
                    "allow_multiple": {
                        "type": "boolean",
                        "default": False,
                        "description": "Allow multiple selections.",
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 5,
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Option id, e.g. 'minimal'."},
                                "label": {"type": "string", "description": "Display label."},
                            },
                            "required": ["id", "label"],
                        },
                    },
                },
                "required": ["id", "prompt", "options"],
            },
        }
    },
    "required": ["questions"],
}


class PlanAskQuestionsTool(BaseTool):
    name = "plan_ask_questions"
    description = (
        "Present structured decision questions to the user. "
        "Use when the user's request is ambiguous or has multiple valid approaches. "
        "Questions should be derived from codebase exploration — never generic. "
        "Only call when you genuinely need user input; skip for clear, specific requests."
    )
    parameters = _ASK_QUESTIONS_SCHEMA

    async def execute(self, **kwargs) -> ToolResult:
        questions = kwargs.get("questions")
        if not isinstance(questions, list) or len(questions) == 0:
            return ToolResult(error="'questions' must be a non-empty array.")

        validated: List[Dict[str, Any]] = []
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return ToolResult(error=f"questions[{i}] must be an object.")
            qid = q.get("id")
            prompt = q.get("prompt")
            options = q.get("options")
            if not qid or not isinstance(qid, str):
                return ToolResult(error=f"questions[{i}].id is required (string).")
            if not prompt or not isinstance(prompt, str):
                return ToolResult(error=f"questions[{i}].prompt is required (string).")
            if not isinstance(options, list) or len(options) < 2:
                return ToolResult(error=f"questions[{i}].options must be an array with >= 2 entries.")

            validated.append({
                "id": qid,
                "prompt": prompt,
                "allow_multiple": bool(q.get("allow_multiple", False)),
                "options": options,
            })

        return ToolResult(
            output=f"Questions submitted ({len(validated)}). Waiting for user response.",
            metadata={
                "plan_action": "questions_submitted",
                "questions": validated,
            },
        )


# ── plan_write_draft ────────────────────────────────────────────────

_WRITE_DRAFT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "One-sentence goal describing what the plan achieves.",
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Explicit assumptions made while researching.",
        },
        "research_notes": {
            "type": "string",
            "description": "Markdown: key files read, existing patterns found, constraints uncovered during exploration.",
        },
        "steps": {
            "type": "array",
            "minItems": 1,
            "description": "Ordered implementation steps.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "details": {"type": "string", "description": "Markdown with file:line refs and concrete changes."},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                    "parallel_group": {"type": "string", "description": "Optional group for parallel execution."},
                },
                "required": ["id", "title"],
            },
        },
        "todos": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "acceptance_criteria": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}, "default": []},
                    "parallel_group": {"type": "string"},
                },
                "required": ["id", "title"],
            },
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Risks with suggested mitigations.",
        },
        "verification": {
            "type": "array",
            "items": {"type": "string"},
            "description": "End-to-end verification steps to confirm the plan works.",
        },
        "markdown_body": {
            "type": "string",
            "description": "Full plan in markdown for human review. Include all sections.",
        },
    },
    "required": ["goal", "assumptions", "research_notes", "steps", "todos", "risks", "verification", "markdown_body"],
}


class PlanWriteDraftTool(BaseTool):
    name = "plan_write_draft"
    description = (
        "Submit a complete, actionable plan for user review. "
        "Only call after you have explored the codebase with read-only tools. "
        "Every step/todo must reference concrete file paths and line numbers. "
        "After submission, wait — the user will approve, reject, or request changes."
    )
    parameters = _WRITE_DRAFT_SCHEMA

    async def execute(self, **kwargs) -> ToolResult:
        # Basic validation
        goal = kwargs.get("goal", "")
        if not goal or not isinstance(goal, str):
            return ToolResult(error="'goal' is required (non-empty string).")

        assumptions = kwargs.get("assumptions", [])
        if not isinstance(assumptions, list):
            return ToolResult(error="'assumptions' must be an array of strings.")

        research_notes = kwargs.get("research_notes", "")
        if not isinstance(research_notes, str):
            return ToolResult(error="'research_notes' must be a string.")

        steps = kwargs.get("steps", [])
        if not isinstance(steps, list) or len(steps) == 0:
            return ToolResult(error="'steps' must be a non-empty array.")

        todos = kwargs.get("todos", [])
        if not isinstance(todos, list) or len(todos) == 0:
            return ToolResult(error="'todos' must be a non-empty array.")

        risks = kwargs.get("risks", [])
        if not isinstance(risks, list):
            return ToolResult(error="'risks' must be an array of strings.")

        verification = kwargs.get("verification", [])
        if not isinstance(verification, list):
            return ToolResult(error="'verification' must be an array of strings.")

        markdown_body = kwargs.get("markdown_body", "")
        if not isinstance(markdown_body, str) or not markdown_body.strip():
            return ToolResult(error="'markdown_body' is required (non-empty markdown string).")

        return ToolResult(
            output="Plan draft submitted for review.",
            metadata={
                "plan_action": "draft_submitted",
                "payload": {
                    "goal": goal,
                    "assumptions": assumptions,
                    "research_notes": research_notes,
                    "steps": steps,
                    "todos": todos,
                    "risks": risks,
                    "verification": verification,
                    "markdown_body": markdown_body,
                },
            },
        )
