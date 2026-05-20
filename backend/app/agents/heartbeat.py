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

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.manager import AgentManager
from app.agents.learnings import LearningsEngine

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

_DURABLE_MEMORY_PATTERNS = [
    r"(请记住|帮我记住|记住一下|以后记得|remember this|please remember)",
    r"(我(?:更)?(?:喜欢|偏好|希望|习惯|需要|不喜欢|不想|不要|默认))",
    r"(以后|之后|下次).{0,24}(?:默认|优先|不要|别|记得|按照)",
    r"(决定|确认|同意|定下来|产品原则|原则锁定|success criteria|decision)",
]

_SENSITIVE_MEMORY_PATTERNS = [
    r"(api[_ -]?key|secret|token|password|密码|密钥|私钥|credential)",
]

_MAX_AUTO_MEMORY_ITEMS = 8
_MAX_MEMORY_CONTENT_CHARS = 360


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
            "handoff_written": False,
            "skipped_duplicate": False,
            "memory_items_stored": 0,
            "learnings_recorded": 0,
            "feature_requests_recorded": 0,
            "todos_found": 0,
            "mood_updated": False,
            "dream_triggered": False,
            "dream_result": None,
            "dream_error": "",
            "memory_error": "",
        }
        signature = cls._session_signature(messages)
        if not signature:
            return result
        if cls._is_duplicate_session_signature(signature):
            result["skipped_duplicate"] = True
            return result

        # 1. Extract key info from conversation and write diary
        diary_content = cls._extract_diary_content(messages)
        if diary_content:
            path = AgentManager.write_diary_entry(diary_content)
            if path:
                result["diary_written"] = True
                logger.info("Heartbeat: diary written to %s", path)

        # 2. Write session handoff and auto-promote obvious memory candidates.
        try:
            handoff_summary = cls._build_session_handoff(messages, session_id)
            if handoff_summary:
                result["handoff_written"] = cls._write_session_handoff(handoff_summary)
            result["memory_items_stored"] = cls._store_auto_memory_items(
                messages=messages,
                session_id=session_id,
                diary_content=diary_content,
                handoff_summary=handoff_summary,
            )
            learning_counts = cls._record_learning_signals(messages)
            result["learnings_recorded"] = learning_counts["learnings"]
            result["feature_requests_recorded"] = learning_counts["feature_requests"]
        except Exception as e:
            logger.warning("Heartbeat: automatic memory extraction failed: %s", e)
            result["memory_error"] = str(e)

        # 3. Scan for pending todos
        todos = cls._scan_todos(messages)
        if todos:
            result["todos_found"] = len(todos)
            todo_entry = "## Pending TODOs\n\n" + "\n".join(f"- [ ] {t}" for t in todos)
            AgentManager.write_diary_entry(todo_entry)

        # 4. Update mood
        mood_data = cls._analyze_mood(messages)
        if mood_data:
            AgentManager.update_mood(mood_data)
            result["mood_updated"] = True

        # 5. Decide whether to trigger DREAM
        should_dream = cls._should_trigger_dream()
        if should_dream:
            try:
                from app.agents.dream import DreamEngine

                result["dream_result"] = await DreamEngine.run()
                result["dream_triggered"] = True
            except Exception as e:
                logger.warning("Heartbeat: DREAM failed: %s", e)
                result["dream_error"] = str(e)

        # 6. Clean expired memories (entries older than 30 days with no recent references)
        cls._clean_expired_memories()
        cls._mark_session_signature(signature)

        return result

    @classmethod
    def _session_signature(cls, messages: List[Dict[str, Any]]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            text = cls._message_text(msg)
            if text:
                parts.append(f"{role}:{text}")
        if not parts:
            return ""
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    @classmethod
    def _heartbeat_state_path(cls):
        return AgentManager._memory_dir() / "heartbeat_state.json"

    @classmethod
    def _is_duplicate_session_signature(cls, signature: str) -> bool:
        path = cls._heartbeat_state_path()
        try:
            if not path.exists():
                return False
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("last_session_signature") == signature
        except (OSError, json.JSONDecodeError):
            return False

    @classmethod
    def _mark_session_signature(cls, signature: str) -> None:
        path = cls._heartbeat_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "last_session_signature": signature,
                        "updated_at": datetime.now().isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Heartbeat: failed to write heartbeat state: %s", e)

    @classmethod
    def _message_text(cls, msg: Dict[str, Any]) -> str:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        return str(content).strip()

    @classmethod
    def _extract_diary_content(cls, messages: List[Dict[str, Any]]) -> str:
        """Extract key conversation points for the daily diary."""
        lines: List[str] = []
        for msg in messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = cls._message_text(msg)
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
    def _build_session_handoff(cls, messages: List[Dict[str, Any]], session_id: str) -> str:
        """Build a compact handoff for the next Personal Agent session."""
        turns = [
            (msg.get("role", ""), cls._message_text(msg))
            for msg in messages
            if msg.get("role") in ("user", "assistant") and len(cls._message_text(msg)) >= 10
        ]
        if not turns:
            return ""

        recent = turns[-8:]
        todos = cls._scan_todos(messages)
        lines = [
            f"Session: {session_id}",
            "",
            "## Recent context",
        ]
        for role, text in recent:
            label = "User" if role == "user" else "Assistant"
            lines.append(f"- {label}: {cls._truncate(text, 220)}")
        if todos:
            lines.extend(["", "## Pending TODOs"])
            lines.extend(f"- [ ] {todo}" for todo in todos[:5])
        return "\n".join(lines).strip()

    @classmethod
    def _write_session_handoff(cls, summary: str) -> bool:
        path = AgentManager._personal_dir() / "session_handoff.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Session Handoff — {now}\n\n{summary}\n", encoding="utf-8")
            return True
        except OSError as e:
            logger.warning("Heartbeat: failed to write session handoff: %s", e)
            return False

    @classmethod
    def _store_auto_memory_items(
        cls,
        *,
        messages: List[Dict[str, Any]],
        session_id: str,
        diary_content: str,
        handoff_summary: str,
    ) -> int:
        """Store obvious session-end Memory OS items without relying on the agent."""
        from app.agents.memory_os import get_memory_os

        memory_os = get_memory_os()
        today = datetime.now().strftime("%Y-%m-%d")
        stored = 0
        candidates: List[Dict[str, Any]] = []

        if handoff_summary:
            candidates.append({
                "content": handoff_summary,
                "memory_type": "working",
                "source": "heartbeat",
                "source_ref": f"session_end:{today}:{session_id}:handoff",
                "summary": "Session handoff for continuity",
                "tier": "hot",
                "confidence": 0.74,
                "metadata": {"auto_extracted": True, "kind": "handoff", "session_id": session_id},
            })

        if diary_content:
            candidates.append({
                "content": cls._truncate(diary_content, 900),
                "memory_type": "episodic",
                "source": "heartbeat",
                "source_ref": f"session_end:{today}:{session_id}:summary",
                "summary": "Automatic session summary",
                "tier": "warm",
                "confidence": 0.68,
                "metadata": {"auto_extracted": True, "kind": "session_summary", "session_id": session_id},
            })

        for idx, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            text = cls._message_text(msg)
            if not cls._is_durable_memory_candidate(text):
                continue
            candidates.append({
                "content": cls._clean_memory_content(text),
                "memory_type": "semantic",
                "source": "heartbeat",
                "source_ref": f"session_end:{today}:{session_id}:user:{idx}",
                "summary": "User-stated durable preference or decision",
                "tier": "hot" if cls._is_explicit_remember(text) else "warm",
                "confidence": 0.84 if cls._is_explicit_remember(text) else 0.76,
                "metadata": {"auto_extracted": True, "kind": "user_signal", "session_id": session_id},
            })

        for candidate in candidates[:_MAX_AUTO_MEMORY_ITEMS]:
            try:
                memory_os.upsert_item(created_by="heartbeat", **candidate)
                stored += 1
            except Exception as exc:
                logger.info(
                    "Heartbeat: skipped auto memory from %s: %s",
                    candidate.get("source_ref"),
                    exc,
                )
        return stored

    @classmethod
    def _record_learning_signals(cls, messages: List[Dict[str, Any]]) -> Dict[str, int]:
        counts = {"learnings": 0, "feature_requests": 0}
        previous_assistant = ""
        for msg in messages:
            role = msg.get("role")
            text = cls._message_text(msg)
            if not text:
                continue
            if role == "assistant":
                previous_assistant = text
                continue
            if role != "user":
                continue

            correction = LearningsEngine.detect_corrections(text, previous_assistant)
            if correction:
                discovery = f"User correction: {cls._truncate(text, 220)}"
                if LearningsEngine.record_learning(discovery):
                    counts["learnings"] += 1

            feature_request = LearningsEngine.detect_capability_gap(text)
            if feature_request and LearningsEngine.record_feature_request(feature_request):
                counts["feature_requests"] += 1
        return counts

    @classmethod
    def _is_durable_memory_candidate(cls, text: str) -> bool:
        clean = text.strip()
        if len(clean) < 12:
            return False
        if any(re.search(pattern, clean, re.IGNORECASE) for pattern in _SENSITIVE_MEMORY_PATTERNS):
            return False
        return any(re.search(pattern, clean, re.IGNORECASE) for pattern in _DURABLE_MEMORY_PATTERNS)

    @classmethod
    def _is_explicit_remember(cls, text: str) -> bool:
        return bool(re.search(_DURABLE_MEMORY_PATTERNS[0], text, re.IGNORECASE))

    @classmethod
    def _clean_memory_content(cls, text: str) -> str:
        return cls._truncate(re.sub(r"\s+", " ", text).strip(), _MAX_MEMORY_CONTENT_CHARS)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        compact = re.sub(r"\s+", " ", text.strip())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "…"

    @classmethod
    def _scan_todos(cls, messages: List[Dict[str, Any]]) -> List[str]:
        """Scan messages for unfulfilled commitments."""
        todos: List[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = cls._message_text(msg)

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
            content = cls._message_text(msg).lower()
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
