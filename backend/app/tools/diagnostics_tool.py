"""Tool wrapper for diagnostics collector — usable by the agent."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult


class ListDiagnosticsTool(BaseTool):
    name = "list_diagnostics"
    description = (
        "List type checker and linter errors/warnings for the project. "
        "Runs mypy/pyright (Python) or tsc/eslint (TypeScript) automatically. "
        "Use this to check code quality before completing work."
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Specific linter to run (mypy, pyright, tsc, eslint). Omit for auto-detect.",
                },
            },
            "required": [],
        }

    async def execute(self, source: Optional[str] = None) -> ToolResult:
        from app.diagnostics import run_diagnostics, detect_linters
        from app.project_manager import ProjectManager

        project = ProjectManager.get_current()
        if not project:
            return ToolResult(error="No project is currently open")

        sources = [source] if source else None
        results = await run_diagnostics(project["path"], sources)

        if not results:
            return ToolResult(output="No linters found for this project.")

        summary_parts = []
        for r in results:
            summary_parts.append(
                f"## {r.source}: {r.total} problems ({r.errors} errors, {r.warnings} warnings)"
            )
            if r.items:
                for item in r.items[:15]:
                    icon = "🔴" if item.severity == "error" else "🟡" if item.severity == "warning" else "ℹ️"
                    summary_parts.append(
                        f"  {icon} {item.file_path}:{item.line}:{item.column} — {item.message}"
                    )
            if r.total > 15:
                summary_parts.append(f"  ... and {r.total - 15} more")
            if r.total == 0:
                summary_parts.append("  ✅ No problems found")

        return ToolResult(output="\n".join(summary_parts))
