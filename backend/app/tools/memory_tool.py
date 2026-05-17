"""Memory management tools for Personal Agent — memory_search, memory_handoff.

Equivalent to OpenClaw's memory_search and session_handoff patterns.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.agents.manager import AgentManager
from app.tools.base import BaseTool, ToolResult


class MemorySearchTool(BaseTool):
    """Search the Personal Agent's memory files for relevant information.

    Scans MEMORY.md, diary files, and DREAMS.md for matching content.
    Equivalent to OpenClaw's memory_search tool.
    """

    name = "memory_search"
    description = (
        "Search your personal memory files (MEMORY.md, diaries, DREAMS.md) "
        "for information relevant to the current conversation. Use this to "
        "recall user preferences, past decisions, learned patterns, and "
        "important context from previous sessions."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query — keywords or phrase to search for in memory files.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        try:
            results = self._search_memory(query, max_results)
            if not results:
                return ToolResult(output="No matching memories found.")
            output = "## Memory Search Results\n\n"
            for r in results:
                output += f"### {r['source']}\n{r['snippet']}\n\n"
            return ToolResult(output=output)
        except Exception as e:
            return ToolResult(error=f"Memory search failed: {e}")

    def _search_memory(self, query: str, max_results: int) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        query_lower = query.lower()

        # 1. Search MEMORY.md
        mem_path = AgentManager._personal_dir() / "MEMORY.md"
        if mem_path.exists():
            try:
                content = mem_path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if query_lower in line.lower() and line.strip():
                        snippet = line.strip()[:300]
                        results.append({"source": "MEMORY.md", "snippet": snippet})
            except OSError:
                pass

        # 2. Search diary files (memory/YYYY-MM-DD.md)
        mem_dir = AgentManager._memory_dir()
        if mem_dir.exists():
            for diary in sorted(mem_dir.glob("*.md"), reverse=True)[:30]:
                try:
                    content = diary.read_text(encoding="utf-8")
                    if query_lower in content.lower():
                        # Extract relevant paragraph
                        for para in content.split("\n"):
                            if query_lower in para.lower() and para.strip():
                                snippet = para.strip()[:300]
                                results.append({"source": f"diary/{diary.name}", "snippet": snippet})
                except OSError:
                    continue

        # 3. Search DREAMS.md
        dreams_path = AgentManager._personal_dir() / "DREAMS.md"
        if dreams_path.exists():
            try:
                content = dreams_path.read_text(encoding="utf-8")
                if query_lower in content.lower():
                    for line in content.split("\n"):
                        if query_lower in line.lower() and line.strip():
                            snippet = line.strip()[:300]
                            results.append({"source": "DREAMS.md", "snippet": snippet})
            except OSError:
                pass

        return results[:max_results]


class MemoryHandoffTool(BaseTool):
    """Write a session handoff summary for the next session.

    Equivalent to OpenClaw's session_handoff.md pattern.
    The agent calls this at the end of a session to pass critical context
    to its future self.
    """

    name = "memory_handoff_write"
    description = (
        "Write a session handoff summary that your future self will read at "
        "the start of the next session. Include: key decisions made, tasks "
        "completed, tasks still pending, important context, and mistakes to "
        "avoid repeating. This is how you maintain continuity across sessions."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "The handoff summary — key context your future self needs to know.",
            },
        },
        "required": ["summary"],
    }

    async def execute(self, summary: str) -> ToolResult:
        try:
            path = AgentManager._personal_dir() / "session_handoff.md"
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = (
                f"# Session Handoff — {now}\n\n"
                f"{summary}\n"
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry, encoding="utf-8")
            return ToolResult(output=f"Handoff written to session_handoff.md ({len(summary)} chars)")
        except OSError as e:
            return ToolResult(error=f"Failed to write handoff: {e}")


class MemoryListTool(BaseTool):
    """List available memory files with summaries."""

    name = "memory_list"
    description = (
        "List your personal memory files (diaries, MEMORY.md, DREAMS.md) "
        "with their sizes and last-modified dates. Use this to understand "
        "what memory data is available before searching."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self) -> ToolResult:
        try:
            lines = ["## Memory Files\n"]
            mem_dir = AgentManager._memory_dir()

            # MEMORY.md
            mem_path = AgentManager._personal_dir() / "MEMORY.md"
            if mem_path.exists():
                size = mem_path.stat().st_size
                lines.append(f"- MEMORY.md ({size / 1024:.1f} KB)")

            # Diaries
            if mem_dir.exists():
                diaries = sorted(mem_dir.glob("*.md"), reverse=True)
                lines.append(f"- Diaries: {len(diaries)} files")
                for d in diaries[:7]:
                    size = d.stat().st_size
                    lines.append(f"  - {d.stem} ({size / 1024:.1f} KB)")

            # DREAMS.md
            dreams_path = AgentManager._personal_dir() / "DREAMS.md"
            if dreams_path.exists():
                size = dreams_path.stat().st_size
                lines.append(f"- DREAMS.md ({size / 1024:.1f} KB)")

            # Handoff
            handoff_path = AgentManager._personal_dir() / "session_handoff.md"
            if handoff_path.exists():
                size = handoff_path.stat().st_size
                lines.append(f"- session_handoff.md ({size / 1024:.1f} KB)")

            return ToolResult(output="\n".join(lines))
        except Exception as e:
            return ToolResult(error=f"Memory list failed: {e}")
