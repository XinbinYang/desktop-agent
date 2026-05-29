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

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.memory_ingestion import MemoryIngestionEngine
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
_SESSION_SIGNATURE_HISTORY_LIMIT = 50
_DREAM_CHECKPOINT_SIZE_THRESHOLD = 50 * 1024
_locks_by_loop: dict[int, asyncio.Lock] = {}


class HeartbeatEngine:
    """Periodic memory maintenance triggered on session end."""

    DREAM_DIARY_SIZE_THRESHOLD = _DREAM_CHECKPOINT_SIZE_THRESHOLD
    DREAM_SESSION_COUNT_THRESHOLD = 5

    @classmethod
    def _maintenance_lock(cls) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        key = id(loop)
        lock = _locks_by_loop.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks_by_loop[key] = lock
        return lock

    @classmethod
    async def on_session_end(
        cls,
        messages: List[Dict[str, Any]],
        session_id: str,
        *,
        agent_type: str = "personal",
    ) -> Dict[str, Any]:
        """Execute heartbeat tasks after a session ends.

        Returns a summary dict for logging / event emission.
        """
        if agent_type != "personal" or session_id.startswith("session_coding"):
            return {
                "diary_written": False,
                "handoff_written": False,
                "skipped_duplicate": False,
                "skipped_non_personal": True,
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
        async with cls._maintenance_lock():
            return await cls._on_personal_session_end(messages, session_id)

    @classmethod
    async def _on_personal_session_end(cls, messages: List[Dict[str, Any]], session_id: str) -> Dict[str, Any]:
        messages = cls._normalize_transcript_messages(messages)
        result: Dict[str, Any] = {
            "diary_written": False,
            "handoff_written": False,
            "skipped_duplicate": False,
            "skipped_non_personal": False,
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
        if not messages or not any(msg.get("role") == "user" for msg in messages):
            return result
        signature = cls._session_signature(messages)
        if not signature:
            return result
        state = cls._read_heartbeat_state()
        if cls._is_duplicate_session_signature(signature, state):
            result["skipped_duplicate"] = True
            return result
        next_session_count = int(state.get("sessions_since_last_dream") or 0) + 1

        # 1-2. Process only the new turn delta, then write diary/handoff/memory records.
        delta_messages: List[Dict[str, Any]] = []
        diary_content = ""
        handoff_summary = ""
        try:
            ingestion = await MemoryIngestionEngine.ingest_session_delta(
                messages,
                session_id,
                state=state,
            )
            result["diary_written"] = bool(ingestion.get("diary_written"))
            result["handoff_written"] = bool(ingestion.get("handoff_written"))
            result["memory_items_stored"] = int(ingestion.get("memory_items_stored") or 0)
            diary_content = str(ingestion.get("diary_content") or "")
            handoff_summary = str(ingestion.get("handoff_summary") or "")
            raw_delta = ingestion.get("delta_messages")
            if isinstance(raw_delta, list):
                delta_messages = [m for m in raw_delta if isinstance(m, dict)]
            state_patch = ingestion.get("state_patch")
            if isinstance(state_patch, dict) and state_patch:
                cls._merge_heartbeat_state(state_patch)
            learning_counts = cls._record_learning_signals(delta_messages)
            result["learnings_recorded"] = learning_counts["learnings"]
            result["feature_requests_recorded"] = learning_counts["feature_requests"]
        except Exception as e:
            logger.warning("Heartbeat: automatic memory extraction failed: %s", e)
            result["memory_error"] = str(e)

        # 3. Scan for pending todos
        todos = cls._scan_todos(delta_messages)
        if todos:
            result["todos_found"] = len(todos)
            todo_entry = "## Pending TODOs\n\n" + "\n".join(f"- [ ] {t}" for t in todos)
            marker = MemoryIngestionEngine._stable_marker_id(session_id, "todos", *(todos[:5]))
            AgentManager.upsert_diary_entry(todo_entry, marker_id=f"todos:{marker}", heading="Pending TODOs")

        # 4. Update mood
        mood_data = cls._analyze_mood(delta_messages)
        if mood_data:
            AgentManager.update_mood(mood_data)
            result["mood_updated"] = True

        # 5. Decide whether to trigger DREAM
        should_dream = cls._should_trigger_dream(state=state, session_count_override=next_session_count)
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
        cls._mark_session_signature(
            signature,
            sessions_since_last_dream=0 if result["dream_triggered"] else next_session_count,
        )

        return result

    @classmethod
    def _merge_heartbeat_state(cls, patch: Dict[str, Any]) -> None:
        state = cls._read_heartbeat_state()
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(state.get(key), dict):
                state[key] = {**state[key], **value}
            else:
                state[key] = value
        state["updated_at"] = datetime.now().isoformat()
        cls._write_heartbeat_state(state)

    @classmethod
    def _message_context_epoch(cls, msg: Dict[str, Any]) -> int:
        try:
            return int(msg.get("context_epoch") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _normalize_transcript_messages(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep only the newest user/assistant transcript epoch for memory tasks."""
        visible: List[Dict[str, Any]] = []
        has_epoch = False
        for msg in messages or []:
            if msg.get("role") not in ("user", "assistant"):
                continue
            if msg.get("source") in ("internal", "command_notice"):
                continue
            if not cls._message_text(msg):
                continue
            if "context_epoch" in msg:
                has_epoch = True
            visible.append(msg)
        if not visible:
            return []
        if not has_epoch:
            return visible
        newest_epoch = max(cls._message_context_epoch(msg) for msg in visible)
        return [
            msg
            for msg in visible
            if cls._message_context_epoch(msg) == newest_epoch
        ]

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
    def _read_heartbeat_state(cls) -> Dict[str, Any]:
        path = cls._heartbeat_state_path()
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def _write_heartbeat_state(cls, state: Dict[str, Any]) -> None:
        path = cls._heartbeat_state_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning("Heartbeat: failed to write heartbeat state: %s", e)

    @classmethod
    def _is_duplicate_session_signature(cls, signature: str, state: Optional[Dict[str, Any]] = None) -> bool:
        state = state if state is not None else cls._read_heartbeat_state()
        signatures = state.get("last_session_signatures")
        if isinstance(signatures, list) and signature in signatures:
            return True
        return state.get("last_session_signature") == signature

    @classmethod
    def _mark_session_signature(cls, signature: str, *, sessions_since_last_dream: int) -> None:
        state = cls._read_heartbeat_state()
        signatures = state.get("last_session_signatures")
        if not isinstance(signatures, list):
            signatures = []
        signatures = [str(s) for s in signatures if s]
        if signature in signatures:
            signatures.remove(signature)
        signatures.append(signature)
        state["last_session_signatures"] = signatures[-_SESSION_SIGNATURE_HISTORY_LIMIT:]
        state["last_session_signature"] = signature
        state["last_heartbeat_at"] = datetime.now().isoformat()
        state["updated_at"] = state["last_heartbeat_at"]
        state["sessions_since_last_dream"] = max(0, int(sessions_since_last_dream))
        cls._write_heartbeat_state(state)

    @classmethod
    def dream_pending_stats(cls, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = state if state is not None else cls._read_heartbeat_state()
        checkpoints = state.get("dream_checkpoints")
        if not isinstance(checkpoints, dict):
            checkpoints = {}
        mem_dir = AgentManager._memory_dir()
        pending_bytes = 0
        pending_files = 0
        if mem_dir.exists():
            for diary in mem_dir.glob("*.md"):
                try:
                    stat = diary.stat()
                except OSError:
                    continue
                checkpoint = checkpoints.get(diary.name) if isinstance(checkpoints.get(diary.name), dict) else {}
                processed_size = int(checkpoint.get("size") or 0)
                delta = stat.st_size - processed_size
                if delta > 0:
                    pending_bytes += delta
                    pending_files += 1
        forgotten = AgentManager._personal_dir() / "forgotten.log"
        forgotten_size = 0
        try:
            forgotten_size = forgotten.stat().st_size if forgotten.exists() else 0
        except OSError:
            forgotten_size = 0
        return {
            "pending_diary_bytes": pending_bytes,
            "pending_diary_kb": round(pending_bytes / 1024, 1),
            "pending_diary_files": pending_files,
            "forgotten_log_size_mb": round(forgotten_size / 1024 / 1024, 2),
        }

    @classmethod
    def memory_status_diagnostics(cls) -> Dict[str, Any]:
        state = cls._read_heartbeat_state()
        try:
            lock_active = cls._maintenance_lock().locked()
        except RuntimeError:
            lock_active = False
        return {
            **cls.dream_pending_stats(state),
            "last_heartbeat_at": state.get("last_heartbeat_at", ""),
            "last_dream_at": state.get("last_dream_at", ""),
            "maintenance_lock_active": lock_active,
        }

    @classmethod
    def mark_dream_complete(cls) -> None:
        state = cls._read_heartbeat_state()
        checkpoints: Dict[str, Any] = {}
        mem_dir = AgentManager._memory_dir()
        if mem_dir.exists():
            for diary in mem_dir.glob("*.md"):
                try:
                    stat = diary.stat()
                    checkpoints[diary.name] = {
                        "size": int(stat.st_size),
                        "mtime": float(stat.st_mtime),
                        "updated_at": datetime.now().isoformat(),
                    }
                except OSError:
                    continue
        now = datetime.now().isoformat()
        state["dream_checkpoints"] = checkpoints
        state["last_dream_at"] = now
        state["sessions_since_last_dream"] = 0
        state["updated_at"] = now
        cls._write_heartbeat_state(state)

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
        context_epoch = max((cls._message_context_epoch(msg) for msg in messages), default=0)
        source_prefix = f"session_end:{today}:{session_id}:epoch:{context_epoch}"
        stored = 0
        candidates: List[Dict[str, Any]] = []

        if handoff_summary:
            candidates.append({
                "content": handoff_summary,
                "memory_type": "working",
                "source": "heartbeat",
                "source_ref": f"{source_prefix}:handoff",
                "summary": "Session handoff for continuity",
                "tier": "hot",
                "confidence": 0.74,
                "metadata": {"auto_extracted": True, "kind": "handoff", "session_id": session_id},
                "dedupe_key": f"heartbeat:{session_id}:{context_epoch}:handoff",
            })

        if diary_content:
            candidates.append({
                "content": cls._truncate(diary_content, 900),
                "memory_type": "episodic",
                "source": "heartbeat",
                "source_ref": f"{source_prefix}:summary",
                "summary": "Automatic session summary",
                "tier": "warm",
                "confidence": 0.68,
                "metadata": {"auto_extracted": True, "kind": "session_summary", "session_id": session_id},
                "dedupe_key": f"heartbeat:{session_id}:{context_epoch}:summary",
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
                "source_ref": f"{source_prefix}:user:{idx}",
                "summary": "User-stated durable preference or decision",
                "tier": "hot" if cls._is_explicit_remember(text) else "warm",
                "confidence": 0.84 if cls._is_explicit_remember(text) else 0.76,
                "metadata": {"auto_extracted": True, "kind": "user_signal", "session_id": session_id},
                "dedupe_key": f"heartbeat:{session_id}:{context_epoch}:user:{idx}",
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
    def _should_trigger_dream(
        cls,
        state: Optional[Dict[str, Any]] = None,
        session_count_override: Optional[int] = None,
    ) -> bool:
        """Check whether incremental unprocessed diary content should trigger DREAM."""
        stats = cls.dream_pending_stats(state)
        if stats["pending_diary_bytes"] <= 0:
            return False
        if stats["pending_diary_bytes"] >= cls.DREAM_DIARY_SIZE_THRESHOLD:
            return True
        if session_count_override is None:
            state = state if state is not None else cls._read_heartbeat_state()
            session_count_override = int(state.get("sessions_since_last_dream") or 0)
        return session_count_override >= cls.DREAM_SESSION_COUNT_THRESHOLD

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
