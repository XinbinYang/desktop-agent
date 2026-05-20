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
            from app.agents.memory_os import get_memory_os
            items = get_memory_os().search(query=query, limit=max_results)
            if items:
                output = "## Memory Search Results\n\n"
                for item in items:
                    output += (
                        f"### {item['source_ref']} "
                        f"({item['memory_type']}, {item['tier']}, score {item.get('score', 0):.2f})\n"
                        f"ID: {item['id']}\n"
                        f"{item['summary'] or item['content'][:300]}\n\n"
                    )
                return ToolResult(output=output)
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


class MemoryRememberTool(BaseTool):
    """Store a structured item in the Personal Memory OS."""

    name = "memory_remember"
    description = (
        "Write a structured Personal Memory OS item when the user states a durable "
        "preference, fact, decision, reusable workflow, or explicit identity update. "
        "Use semantic for stable facts/preferences, episodic for session events, "
        "procedural for reusable how-to knowledge, working for short-lived continuity, "
        "and identity only for explicit high-confidence identity/profile updates."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The exact memory content to store. Keep it concise and factual.",
            },
            "memory_type": {
                "type": "string",
                "enum": ["working", "episodic", "semantic", "procedural", "identity"],
                "description": "Memory layer for this item.",
            },
            "summary": {
                "type": "string",
                "description": "Optional short summary shown in search results.",
            },
            "tier": {
                "type": "string",
                "enum": ["hot", "warm", "cold", "archived"],
                "description": "Attention tier. Use hot only for currently important memory.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence from 0 to 1. Identity memories should be at least 0.9.",
            },
            "source_ref": {
                "type": "string",
                "description": "Optional source note, e.g. 'user_explicit:current_session'.",
            },
        },
        "required": ["content", "memory_type"],
    }

    async def execute(
        self,
        content: str,
        memory_type: str,
        summary: str = "",
        tier: str = "warm",
        confidence: float = 0.75,
        source_ref: str = "agent:current_session",
    ) -> ToolResult:
        try:
            if memory_type == "identity" and confidence < 0.9:
                return ToolResult(error="Identity memories require confidence >= 0.9 and explicit user support.")
            from app.agents.memory_os import get_memory_os
            item = get_memory_os().upsert_item(
                content=content,
                memory_type=memory_type,
                source="agent",
                source_ref=source_ref or "agent:current_session",
                summary=summary,
                tier=tier or "warm",
                confidence=confidence,
                created_by="agent",
            )
            return ToolResult(
                output=(
                    "Stored memory "
                    f"{item['id']} ({item['memory_type']}, {item['tier']}, confidence {item['confidence']:.2f})."
                ),
                metadata={"item": item},
            )
        except Exception as e:
            return ToolResult(error=f"Memory remember failed: {e}")


class MemoryUpdateTool(BaseTool):
    """Update an existing Personal Memory OS item."""

    name = "memory_update"
    description = (
        "Update an existing Memory OS item after searching for its id. Use this to "
        "correct stale, contradictory, or more precise memories instead of creating duplicates."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Memory item id from memory_search results."},
            "content": {"type": "string", "description": "Optional replacement content."},
            "summary": {"type": "string", "description": "Optional replacement summary."},
            "memory_type": {
                "type": "string",
                "enum": ["working", "episodic", "semantic", "procedural", "identity"],
                "description": "Optional replacement memory type.",
            },
            "tier": {
                "type": "string",
                "enum": ["hot", "warm", "cold", "archived"],
                "description": "Optional replacement attention tier.",
            },
            "confidence": {"type": "number", "description": "Optional confidence from 0 to 1."},
        },
        "required": ["item_id"],
    }

    async def execute(
        self,
        item_id: str,
        content: str = "",
        summary: str = "",
        memory_type: str = "",
        tier: str = "",
        confidence: float | None = None,
    ) -> ToolResult:
        try:
            updates: Dict[str, Any] = {}
            if content:
                updates["content"] = content
            if summary:
                updates["summary"] = summary
            if memory_type:
                updates["memory_type"] = memory_type
            if tier:
                updates["tier"] = tier
            if confidence is not None:
                updates["confidence"] = confidence
            if not updates:
                return ToolResult(error="No memory updates provided.")
            from app.agents.memory_os import get_memory_os
            item = get_memory_os().patch_item(item_id, updates, actor="agent")
            if not item:
                return ToolResult(error=f"Memory item not found: {item_id}")
            return ToolResult(
                output=f"Updated memory {item_id} ({item['memory_type']}, {item['tier']}).",
                metadata={"item": item},
            )
        except Exception as e:
            return ToolResult(error=f"Memory update failed: {e}")


class MemoryForgetTool(BaseTool):
    """Soft-delete a Personal Memory OS item."""

    name = "memory_forget"
    description = (
        "Soft-delete a Memory OS item after the user asks to forget it or confirms "
        "it is wrong. Search first, then pass the exact item id. This does not erase "
        "audit history."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "Memory item id from memory_search results."},
        },
        "required": ["item_id"],
    }

    async def execute(self, item_id: str) -> ToolResult:
        try:
            from app.agents.memory_os import get_memory_os
            ok = get_memory_os().delete_item(item_id, actor="agent")
            if not ok:
                return ToolResult(error=f"Memory item not found: {item_id}")
            return ToolResult(output=f"Forgot memory {item_id}.")
        except Exception as e:
            return ToolResult(error=f"Memory forget failed: {e}")


class MemoryRebuildTool(BaseTool):
    """Rebuild the Personal Memory OS index from workspace files."""

    name = "memory_rebuild"
    description = (
        "Rebuild the Memory OS index from MEMORY.md, diaries, DREAMS.md, handoff, "
        "identity files, and learnings when search looks stale or after memory file migration."
    )
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self) -> ToolResult:
        try:
            from app.agents.memory_os import get_memory_os
            result = get_memory_os().rebuild_from_workspace()
            return ToolResult(
                output=(
                    f"Memory OS rebuilt: {result.get('indexed', 0)} indexed, "
                    f"{result.get('skipped', 0)} skipped."
                ),
                metadata=result,
            )
        except Exception as e:
            return ToolResult(error=f"Memory rebuild failed: {e}")


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
            from app.agents.memory_os import get_memory_os
            status = get_memory_os().status()
            lines = ["## Memory Files\n"]
            lines.append(
                "Memory OS: "
                f"{status.get('total_items', 0)} indexed items "
                f"(vector: {'available' if status.get('vector_available') else 'unavailable'})\n"
            )
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
