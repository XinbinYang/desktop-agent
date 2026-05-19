"""HEARTBEAT Engine — periodic memory maintenance for Personal Agent.

Triggers on session end (WebSocket disconnect). Performs:
- Write daily diary entries
- Scan for pending todos
- Update mood.json
- Decide whether to trigger DREAM
- Clean expired/contradictory memories

Reference: OpenClaw Heartbeat + Claude Code Auto Dream trigger conditions.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.manager import AgentManager

logger = logging.getLogger(__name__)

# Keywords that indicate an unfulfilled commitment
_TODO_PATTERNS = [
    r"(我会|我来|我帮你|稍后|接下来|等一下|回头)",
    r"(TODO|todo|FIXME|fixme|HACK|hack)",
    r"(还没|尚未|有待|待做|待办)",
]

# Simple sentiment indicators for mood analysis
_POSITIVE_WORDS = ["谢谢", "好的", "很好", "不错", "完美", "棒", "喜欢", "great", "thanks", "awesome", "good", "love"]
_NEGATIVE_WORDS = ["不对", "错了", "不行", "不好", "糟糕", "失败", "错误", "wrong", "bad", "error", "fail", "sorry"]


class HeartbeatEngine:
    """Periodic memory maintenance triggered on session end."""

    DREAM_DIARY_SIZE_THRESHOLD = 5 * 1024  # 5KB
    DREAM_SESSION_COUNT_THRESHOLD = 5

    @classmethod
    async def on_session_end(cls, messages: List[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
        """Execute heartbeat tasks after a session ends.

        Returns a summary dict for logging / event emission.
        """
        result: Dict[str, Any] = {
            "diary_written": False,
            "todos_found": 0,
            "mood_updated": False,
            "dream_triggered": False,
            "dream_result": None,
            "dream_error": "",
        }

        # 1. Extract key info from conversation and write diary
        diary_content = cls._extract_diary_content(messages)
        if diary_content:
            path = AgentManager.write_diary_entry(diary_content)
            if path:
                result["diary_written"] = True
                logger.info("Heartbeat: diary written to %s", path)

        # 2. Scan for pending todos
        todos = cls._scan_todos(messages)
        if todos:
            result["todos_found"] = len(todos)
            todo_entry = "## Pending TODOs\n\n" + "\n".join(f"- [ ] {t}" for t in todos)
            AgentManager.write_diary_entry(todo_entry)

        # 3. Update mood
        mood_data = cls._analyze_mood(messages)
        if mood_data:
            AgentManager.update_mood(mood_data)
            result["mood_updated"] = True

        # 4. Decide whether to trigger DREAM
        should_dream = cls._should_trigger_dream()
        if should_dream:
            try:
                from app.agents.dream import DreamEngine

                result["dream_result"] = await DreamEngine.run()
                result["dream_triggered"] = True
            except Exception as e:
                logger.warning("Heartbeat: DREAM failed: %s", e)
                result["dream_error"] = str(e)

        # 5. Clean expired memories (entries older than 30 days with no recent references)
        cls._clean_expired_memories()

        return result

    @classmethod
    def _extract_diary_content(cls, messages: List[Dict[str, Any]]) -> str:
        """Extract key conversation points for the daily diary."""
        lines: List[str] = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )

            content = str(content).strip()
            if not content or len(content) < 10:
                continue

            # Keep a brief summary — first 200 chars
            summary = content[:200]
            if role == "user":
                lines.append(f"- User: {summary}")
            else:
                lines.append(f"- Assistant: {summary}")

        if not lines:
            return ""

        return "## Session Summary\n\n" + "\n".join(lines[:20])  # Cap at 20 entries

    @classmethod
    def _scan_todos(cls, messages: List[Dict[str, Any]]) -> List[str]:
        """Scan messages for unfulfilled commitments."""
        todos: List[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            content = str(content)

            for pattern in _TODO_PATTERNS:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for m in matches:
                    line = content[max(0, content.find(str(m)) - 20):content.find(str(m)) + len(str(m)) + 80]
                    if line not in todos:
                        todos.append(line.strip()[:200])

        return todos[:10]  # Cap at 10

    @classmethod
    def _analyze_mood(cls, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Simple sentiment analysis of the conversation to determine mood."""
        positive_count = 0
        negative_count = 0
        total_words = 0

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            content = str(content).lower()
            words = content.split()
            total_words += len(words)

            for word in _POSITIVE_WORDS:
                if word in content:
                    positive_count += 1
            for word in _NEGATIVE_WORDS:
                if word in content:
                    negative_count += 1

        if total_words == 0:
            return None

        # Determine mood
        ratio = (positive_count - negative_count) / max(total_words / 100, 1)
        if ratio > 0.3:
            mood = "positive"
        elif ratio < -0.3:
            mood = "negative"
        else:
            mood = "neutral"

        return {"current": mood}

    @classmethod
    def _should_trigger_dream(cls) -> bool:
        """Check if DREAM should be triggered based on diary size and session count."""
        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return False

        # Check diary size
        dreams_path = AgentManager._personal_dir() / "DREAMS.md"
        last_dream_mtime = 0.0
        if dreams_path.exists():
            try:
                last_dream_mtime = dreams_path.stat().st_mtime
            except OSError:
                last_dream_mtime = 0.0

        total_size = 0
        diary_count = 0
        for f in mem_dir.glob("*.md"):
            try:
                if f.stat().st_mtime <= last_dream_mtime:
                    continue
                total_size += f.stat().st_size
                diary_count += 1
            except OSError:
                pass

        if total_size > cls.DREAM_DIARY_SIZE_THRESHOLD:
            return True

        # Check session count since last consolidation
        # (Simplified: if diary_count >= threshold, trigger)
        if diary_count >= cls.DREAM_SESSION_COUNT_THRESHOLD:
            return True

        return False

    @classmethod
    def _clean_expired_memories(cls) -> None:
        """Remove diary files older than 90 days."""
        mem_dir = AgentManager._memory_dir()
        if not mem_dir.exists():
            return

        from datetime import timedelta

        cutoff = datetime.now() - timedelta(days=90)
        for f in mem_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < cutoff:
                    f.unlink()
                    logger.info("Heartbeat: removed expired diary %s", f.name)
            except OSError:
                pass
