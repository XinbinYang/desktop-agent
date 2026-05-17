"""CognitiveTaskRunner — isolated background session executor.

Runs cognitive tasks (DREAM REM, EVOLUTION reflection, skill analysis)
in fully isolated AgentSession instances that:
- Never share message history with the main WebSocket session
- Never write to sessions/ JSON (no persistence pollution)
- Never notify the frontend (no WebSocket events)
- Communicate results only through the filesystem (AGENTS/ files)

Reference: OpenClaw isolatedSession + lightContext pattern,
           WorkerSession async generator pattern.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agent import AgentSession
from app.config import load_config

logger = logging.getLogger(__name__)


class CognitiveTaskRunner:
    """Execute cognitive background tasks in isolated sessions.

    Design constraints:
    - isolated: true — fresh AgentSession per run, zero shared history
    - light_context: true — minimal system prompt (task instructions only)
    - no_persistence: true — _save() is no-op, sessions/ directory untouched
    - silent: true — no WebSocket events, results go to filesystem only
    """

    # Default model for cognitive tasks (cheaper/faster is fine)
    DEFAULT_MODEL: str | None = None

    @classmethod
    def _resolve_model(cls, model_id: str | None = None) -> str:
        """Resolve the model to use for cognitive tasks."""
        if model_id:
            return model_id
        if cls.DEFAULT_MODEL:
            return cls.DEFAULT_MODEL
        try:
            return load_config().settings.default_model
        except Exception:
            return "kimi-for-coding"

    @classmethod
    async def run_task(
        cls,
        instruction: str,
        *,
        task_name: str = "cognitive",
        model_id: str | None = None,
        max_iterations: int = 10,
        temperature: float = 0.5,
        context_files: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Run a cognitive task in an isolated AgentSession.

        Args:
            instruction: The task description / system prompt for the isolated session.
            task_name: Short identifier for logging (e.g., "dream_rem").
            model_id: Optional model override.
            max_iterations: Max ReAct loop iterations (default 10).
            temperature: LLM temperature for the task.
            context_files: Optional list of {name, content} dicts to inject as context.

        Returns:
            Dict with keys: status, result, iterations, duration_ms, error (if any).
        """
        session_id = f"bg_{task_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        model = cls._resolve_model(model_id)
        started_at = datetime.now()

        logger.info("CognitiveTaskRunner [%s] starting (session=%s, model=%s)", task_name, session_id, model)

        # Create a fully isolated AgentSession.
        # agent_type="personal" ensures no coding_run/worktree overhead.
        session = AgentSession(
            model_id=model,
            session_id=session_id,
            role_id="desktop-agent",
            agent_type="personal",
        )

        # Disable persistence — this session must never appear in sessions/ listings
        session._save = lambda: None  # type: ignore[method-assign]

        # Limit iterations for background tasks
        session.max_iterations = max_iterations

        # Replace the system prompt with a minimal task-specific context.
        # We strip the full persona and inject only what the task needs.
        minimal_prompt = cls._build_minimal_prompt(instruction, context_files)
        session.messages[0] = {"role": "system", "content": minimal_prompt}

        result_text = ""
        iterations = 0
        error = None

        try:
            async for event in session.run(instruction):
                etype = event.get("type", "")
                edata = event.get("data", {})

                if etype == "content":
                    result_text += edata.get("text", "")
                elif etype == "status" and edata.get("status") == "completed":
                    iterations = edata.get("iteration", iterations)
                elif etype == "run_completed":
                    iterations = edata.get("iteration", iterations) or iterations

                # All other events (tool_call, reasoning, image, etc.) are silently consumed.
                # No event is forwarded to any WebSocket or frontend.

        except Exception as e:
            error = str(e)
            logger.warning("CognitiveTaskRunner [%s] failed: %s", task_name, e)

        duration_ms = int((datetime.now() - started_at).total_seconds() * 1000)

        logger.info(
            "CognitiveTaskRunner [%s] completed: status=%s, iterations=%d, duration=%dms",
            task_name, "error" if error else "ok", iterations, duration_ms,
        )

        return {
            "status": "error" if error else "completed",
            "result": result_text.strip(),
            "iterations": iterations,
            "duration_ms": duration_ms,
            "session_id": session_id,
            "error": error,
        }

    @classmethod
    def _build_minimal_prompt(
        cls,
        instruction: str,
        context_files: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Build a minimal system prompt for an isolated cognitive session.

        Unlike the main session which loads full persona + memory + diaries,
        this only includes the task instruction and optionally context files.
        """
        parts: List[str] = []

        parts.append("You are a background cognitive agent. Your task is below.")
        parts.append("You have access to file_read and file_write tools for the AGENTS/ workspace.")
        parts.append("You have NO access to browser, desktop, shell, or external tools.")
        parts.append("Respond concisely. Your output will be processed by another system.")
        parts.append("")

        if context_files:
            parts.append("## Context Files\n")
            for cf in context_files:
                name = cf.get("name", "file")
                content = cf.get("content", "")
                max_len = 3000
                if len(content) > max_len:
                    content = content[:max_len] + "\n\n[truncated]"
                parts.append(f"### {name}\n{content}\n")

        parts.append("## Task\n")
        parts.append(instruction)
        parts.append("")
        parts.append("After completing the task, output a concise summary of what you did.")
        parts.append("Do NOT use emoji. Do NOT greet the user. Just do the task and report.")

        return "\n".join(parts)

    @classmethod
    async def run_dream_rem(
        cls,
        passed_entries: List[str],
        candidates: List[str],
        model_id: str | None = None,
    ) -> Dict[str, Any]:
        """Run DREAM REM phase: discover patterns and generate SOUL suggestions.

        Args:
            passed_entries: Entries that passed the deep sleep threshold.
            candidates: All candidate entries from light sleep.

        Returns:
            Dict with patterns and suggestions.
        """
        instruction = (
            "You are analyzing the agent's recent memory consolidation results.\n\n"
            "## Entries that passed the memory consolidation threshold\n"
        )
        for i, entry in enumerate(passed_entries[:20], 1):
            instruction += f"{i}. {entry}\n"

        if candidates:
            instruction += "\n## Other candidates considered\n"
            for i, c in enumerate(candidates[:10], 1):
                if c not in passed_entries:
                    instruction += f"- {c}\n"

        instruction += """
## Your task
1. Look for patterns — recurring themes, user preferences, behavioral patterns
2. Identify associations — how different entries relate to each other
3. Generate 1-3 micro-suggestions for SOUL.md adjustments

Output format:
PATTERNS:
- [pattern description]

SUGGESTIONS:
- [SOUL adjustment suggestion]
"""

        result = await cls.run_task(
            instruction=instruction,
            task_name="dream_rem",
            model_id=model_id,
            max_iterations=5,
        )
        return result

    @classmethod
    async def run_evolution_reflection(
        cls,
        errors_text: str,
        model_id: str | None = None,
    ) -> Dict[str, Any]:
        """Run EVOLUTION reflection phase: extract principles from errors.

        Args:
            errors_text: Content of ERRORS.md.

        Returns:
            Dict with extracted principles.
        """
        instruction = (
            "You are analyzing the agent's recent error log to extract improvement principles.\n\n"
            "## Recent errors\n"
            f"{errors_text[:5000]}\n\n"
            "## Your task\n"
            "Extract 1-5 principle-based rules from these errors. "
            'Format: "When [situation], remember to [action] first." '
            "Focus on actionable, reusable lessons."
        )

        result = await cls.run_task(
            instruction=instruction,
            task_name="evolution_reflection",
            model_id=model_id,
            max_iterations=5,
        )
        return result

    @classmethod
    async def run_skill_crystallization(
        cls,
        task_summaries: List[str],
        model_id: str | None = None,
    ) -> Dict[str, Any]:
        """Run EVOLUTION skill crystallization: analyze successful tasks.

        Args:
            task_summaries: Summaries of recent successful tasks.

        Returns:
            Dict with skill template suggestions.
        """
        instruction = (
            "You are analyzing successful task completions to extract reusable skill patterns.\n\n"
            "## Recent successful tasks\n"
        )
        for i, summary in enumerate(task_summaries[:15], 1):
            instruction += f"{i}. {summary}\n"

        instruction += """
## Your task
1. Identify common task patterns across these successes
2. For each pattern, write a reusable skill template with steps
3. Suggest which patterns could be automated as skills

Output format:
SKILL: [skill_name]
Steps:
1. [step]
2. [step]
---
"""

        result = await cls.run_task(
            instruction=instruction,
            task_name="skill_crystallization",
            model_id=model_id,
            max_iterations=8,
        )
        return result
