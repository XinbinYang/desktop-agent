"""Tool wrapper for integrated test runner — usable by the agent."""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.tools.base import BaseTool, ToolResult
from app.test_runner import run_and_store, detect_framework


class RunTestsTool(BaseTool):
    name = "run_tests"
    description = (
        "Run the project's test suite. Detects pytest/vitest/jest automatically. "
        "Use this before completing work to verify nothing is broken. "
        "Results are cached for the frontend TestsPanel."
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional test filter pattern (passed to pytest -k or vitest -t)",
                },
                "framework": {
                    "type": "string",
                    "enum": ["pytest", "vitest", "jest"],
                    "description": "Force a specific framework instead of auto-detecting",
                },
            },
            "required": [],
        }

    async def execute(self, filter: str = "", framework: Optional[str] = None) -> ToolResult:
        from app.project_manager import ProjectManager

        project = ProjectManager.get_current()
        if not project:
            return ToolResult(error="No project is currently open")

        project_path = project["path"]
        run = await run_and_store(project_path, framework, filter)

        if run.total == 0 and run.errors == 0:
            return ToolResult(output=f"Tests: no tests found. {run.raw_output[:1000]}")

        summary = (
            f"Tests: {run.total} total, {run.passed} passed, {run.failed} failed, "
            f"{run.skipped} skipped, {run.errors} errors ({run.duration_ms}ms)\n\n"
        )
        if run.failed > 0 or run.errors > 0:
            failed_tests = [r for r in run.results if r.status in ("failed", "error")][:10]
            for t in failed_tests:
                summary += f"  FAIL  {t.name} ({t.file_path})\n"
            summary += f"\nRaw output:\n{run.raw_output[:2000]}"
        elif run.passed > 0:
            summary += f"All {run.passed} tests passed."

        return ToolResult(output=summary)
