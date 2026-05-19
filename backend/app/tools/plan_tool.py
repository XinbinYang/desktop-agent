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
            "description": (
                "One to five focused clarifying questions the user must answer. "
                "Ask enough to understand the request; avoid filler."
            ),
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
        "Present one or more structured decision questions to the user. "
        "Use when the user's request is ambiguous or has multiple valid approaches. "
        "Questions should be derived from codebase exploration — never generic. "
        "Batch related blocking decisions when multiple answers are needed to draft a sound plan. "
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
            "description": "Required. One-sentence goal describing what the plan achieves.",
        },
        "context": {
            "type": "string",
            "description": (
                "Optional but recommended. Why this change is needed — the problem/need, "
                "what prompted it, the intended outcome. Rendered as the '任务目标 / Goal' block."
            ),
        },
        "assumptions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional. Explicit assumptions made while researching. Omit if none.",
        },
        "research_notes": {
            "type": "string",
            "description": "Optional. Markdown: key files read, existing patterns found, constraints uncovered during exploration.",
        },
        "steps": {
            "type": "array",
            "description": "Optional/internal. Compatibility field for ordered implementation notes. User-facing plans render todos as Tasks.",
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
            "description": "Required. The only user-visible execution plan, rendered as Tasks. Prefer <= ~15 substantive todos over dozens of micro-todos.",
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
            "description": "Optional. Risks with suggested mitigations. Omit if none.",
        },
        "verification": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional. End-to-end verification steps to confirm the plan works.",
        },
        "critical_files": {
            "type": "array",
            "description": (
                "Optional but recommended. Files to be created/modified with a short change "
                "description each. Rendered as the '关键文件清单 / Critical Files' block."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repo root."},
                    "change": {"type": "string", "description": "Short description of the change."},
                },
                "required": ["path"],
            },
        },
        "markdown_body": {
            "type": "string",
            "description": (
                "Optional. Full plan in markdown for human review. "
                "If omitted, the system auto-generates a readable version from the structured fields — "
                "do NOT duplicate the whole plan here for large plans."
            ),
        },
    },
    "required": ["goal", "todos"],
}


class PlanWriteDraftTool(BaseTool):
    name = "plan_write_draft"
    description = (
        "Submit a complete, actionable plan for user review. "
        "Only call after you have explored the codebase with read-only tools. "
        "Every todo must reference concrete file paths and line numbers when possible. "
        "After submission, wait — the user will approve, reject, or request changes. "
        "Required fields: 'goal', 'todos'. Optional 'steps' is kept only for compatibility/internal notes. Everything else is optional "
        "('markdown_body' is auto-generated if omitted). "
        "Recommended for a high-quality plan: 'context' (why this change — the 任务目标 block), "
        "'critical_files' (files to change — the 关键文件清单 block), and 'verification' (how to test — the 验证 block). "
        "Each todo becomes a numbered PART in the 任务方案 block, so order todos as the implementation approach. "
        "NEVER call this tool with empty arguments. "
        "For large plans, merge work into coarse-grained todos rather than dozens of micro-todos."
    )
    parameters = _WRITE_DRAFT_SCHEMA

    _SKELETON = (
        '{"goal": "<one sentence>", '
        '"todos": [{"id": "t1", "title": "<task>", "acceptance_criteria": "<how to verify>"}]}'
    )

    async def execute(self, **kwargs) -> ToolResult:
        # Empty-args guard: the most common failure mode is the model emitting {}.
        if not kwargs:
            return ToolResult(error=(
                "[ERROR] plan_write_draft was called with EMPTY arguments. "
                "This tool MUST receive a full JSON object. Do not call it with {}. "
                "Required: 'goal' (string), 'todos' (non-empty array). "
                "Optional (omit if large/unneeded): assumptions, research_notes, risks, verification, markdown_body. "
                f"Re-call now with at minimum: {self._SKELETON}"
            ))

        # Aggregate ALL problems into one actionable message instead of failing
        # on the first field — the model needs the full contract to recover.
        errors: List[str] = []

        goal = kwargs.get("goal", "")
        if not goal or not isinstance(goal, str):
            errors.append("'goal' is required (non-empty string).")

        steps = kwargs.get("steps", [])
        if not isinstance(steps, list):
            steps = []

        todos = kwargs.get("todos", [])
        if not isinstance(todos, list) or len(todos) == 0:
            errors.append("'todos' must be a non-empty array of todo objects.")

        # Optional fields: coerce bad/missing values to safe defaults instead of erroring.
        assumptions = kwargs.get("assumptions", [])
        if not isinstance(assumptions, list):
            assumptions = []

        research_notes = kwargs.get("research_notes", "")
        if not isinstance(research_notes, str):
            research_notes = ""

        risks = kwargs.get("risks", [])
        if not isinstance(risks, list):
            risks = []

        verification = kwargs.get("verification", [])
        if not isinstance(verification, list):
            verification = []

        markdown_body = kwargs.get("markdown_body", "")
        if not isinstance(markdown_body, str):
            markdown_body = ""

        context = kwargs.get("context", "")
        if not isinstance(context, str):
            context = ""

        critical_files_raw = kwargs.get("critical_files", [])
        critical_files: List[Dict[str, str]] = []
        if isinstance(critical_files_raw, list):
            for cf in critical_files_raw:
                if isinstance(cf, dict) and cf.get("path"):
                    critical_files.append({
                        "path": str(cf.get("path", "")),
                        "change": str(cf.get("change", "")),
                    })
                elif isinstance(cf, str) and cf.strip():
                    critical_files.append({"path": cf.strip(), "change": ""})

        if errors:
            return ToolResult(error=(
                "[ERROR] plan_write_draft validation failed:\n- "
                + "\n- ".join(errors)
                + "\n\nRequired shape: 'goal' (string), "
                "'todos' (non-empty array). Re-call with ONE complete JSON object — "
                "do NOT send empty arguments. If the plan is large, omit 'markdown_body' "
                "(the system auto-generates a readable version) and use coarse-grained todos. "
                f"Minimal example: {self._SKELETON}"
            ))

        return ToolResult(
            output="Plan draft submitted for review.",
            metadata={
                "plan_action": "draft_submitted",
                "payload": {
                    "goal": goal,
                    "context": context,
                    "assumptions": assumptions,
                    "research_notes": research_notes,
                    "steps": steps,
                    "todos": todos,
                    "risks": risks,
                    "verification": verification,
                    "critical_files": critical_files,
                    "markdown_body": markdown_body,
                },
            },
        )


# ── plan_update_todos ───────────────────────────────────────────────

_UPDATE_TODOS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "updates": {
            "type": "array",
            "minItems": 1,
            "description": "Todo status changes to apply during BUILD execution.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The todo id from the approved plan."},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked", "cancelled"],
                        "description": "New status for this todo.",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short note, e.g. the blocker reason.",
                    },
                },
                "required": ["id", "status"],
            },
        }
    },
    "required": ["updates"],
}


class PlanUpdateTodosTool(BaseTool):
    name = "plan_update_todos"
    description = (
        "Update plan todo statuses during BUILD execution (after the user clicked Build). "
        "Call this RIGHT BEFORE starting a todo (set it 'in_progress') and IMMEDIATELY AFTER "
        "finishing it (set it 'completed') — one todo at a time. Do NOT batch many completions "
        "at the end; the user watches progress tick item-by-item in the plan card. Mark a todo "
        "'blocked' with a note if you hit a real blocker. You may update several todos in one "
        "call (e.g. mark the finished one 'completed' and the next one 'in_progress' together). "
        "NEVER call this tool with empty arguments."
    )
    parameters = _UPDATE_TODOS_SCHEMA

    _SKELETON = '{"updates": [{"id": "t1", "status": "completed"}]}'
    _VALID_STATUS = {"pending", "in_progress", "completed", "blocked", "cancelled"}

    async def execute(self, **kwargs) -> ToolResult:
        if not kwargs:
            return ToolResult(error=(
                "[ERROR] plan_update_todos was called with EMPTY arguments. "
                "Pass a non-empty 'updates' array of {id, status} objects. "
                f"Re-call now with at minimum: {self._SKELETON}"
            ))

        updates = kwargs.get("updates", [])
        if not isinstance(updates, list) or len(updates) == 0:
            return ToolResult(error=(
                "[ERROR] plan_update_todos requires a non-empty 'updates' array of "
                "{id, status} objects. status must be one of "
                "pending|in_progress|completed|blocked|cancelled. "
                f"Minimal example: {self._SKELETON}"
            ))

        clean: List[Dict[str, str]] = []
        for u in updates:
            if not isinstance(u, dict):
                continue
            tid = u.get("id")
            status = u.get("status")
            if not tid or not isinstance(tid, str):
                continue
            if status not in self._VALID_STATUS:
                # Degrade gracefully: skip an unknown status rather than failing the whole call.
                continue
            entry: Dict[str, str] = {"id": tid, "status": status}
            note = u.get("note")
            if isinstance(note, str) and note.strip():
                entry["note"] = note.strip()
            clean.append(entry)

        if not clean:
            return ToolResult(error=(
                "[ERROR] plan_update_todos: no valid updates after validation. Each update "
                "needs a string 'id' and a 'status' of "
                "pending|in_progress|completed|blocked|cancelled. "
                f"Minimal example: {self._SKELETON}"
            ))

        return ToolResult(
            output=f"Applied {len(clean)} todo update(s).",
            metadata={
                "plan_action": "todos_updated",
                "payload": {"updates": clean},
            },
        )
