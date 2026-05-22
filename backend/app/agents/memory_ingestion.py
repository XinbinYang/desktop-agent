"""Delta-based Personal Agent memory ingestion.

The heartbeat receives the current visible transcript after every Personal
turn. This module turns that full transcript into an idempotent per-turn delta
before writing diary and Memory OS records, so long sessions do not keep dumping
their entire history into daily memory files.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from app.agents.manager import AgentManager

logger = logging.getLogger(__name__)

_MAX_DIARY_CHARS = 1400
_MAX_HANDOFF_TURNS = 8
_MAX_MEMORY_CONTENT_CHARS = 360
_MAX_PROCESSED_KEYS = 3000
_MAX_TRACKED_SCOPES = 80
_MIN_MEMORY_CONFIDENCE = 0.6

_DURABLE_MEMORY_PATTERNS = [
    r"(请记住|帮我记住|记住一下|以后记得|remember this|please remember)",
    r"(我(?:更)?(?:喜欢|偏好|希望|习惯|需要|不喜欢|不想|不要|默认))",
    r"(以后|之后|下次).{0,24}(?:默认|优先|不要|别|记得|按照)",
    r"(决定|确认|同意|定下来|产品原则|原则锁定|success criteria|decision)",
    r"(不对|错了|纠正|正确的是|应该是)",
]

_SENSITIVE_MEMORY_PATTERNS = [
    r"(api[_ -]?key|secret|token|password|密码|密钥|私钥|credential)",
    r"(\b\d{3}-\d{2}-\d{4}\b|\b\d{13,19}\b)",
]


@dataclass
class IngestionDelta:
    messages: list[dict[str, Any]]
    context_epoch: int
    scope_key: str
    turn_key: str
    marker_id: str
    processed_keys: list[str]


class MemoryIngestionEngine:
    """Build and persist idempotent memory deltas."""

    @classmethod
    async def ingest_session_delta(
        cls,
        messages: list[dict[str, Any]],
        session_id: str,
        *,
        state: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        state = state if isinstance(state, dict) else {}
        visible = cls._normalize_transcript_messages(messages)
        result: dict[str, Any] = {
            "diary_written": False,
            "handoff_written": False,
            "memory_items_stored": 0,
            "processed_message_count": 0,
            "skipped_no_delta": False,
            "state_patch": {},
            "diary_content": "",
            "handoff_summary": "",
            "delta_messages": [],
        }
        if not visible:
            result["skipped_no_delta"] = True
            return result

        delta = cls._select_delta(visible, session_id, state)
        if not delta.messages:
            result["skipped_no_delta"] = True
            return result
        result["delta_messages"] = delta.messages

        diary_content = cls.build_diary_delta(delta.messages, session_id=session_id)
        if diary_content:
            path = AgentManager.upsert_diary_entry(
                diary_content,
                marker_id=delta.marker_id,
                heading="Session Delta",
            )
            result["diary_written"] = bool(path)
            result["diary_content"] = diary_content

        handoff_summary = cls.build_session_handoff(visible, session_id)
        if handoff_summary:
            result["handoff_written"] = cls.write_session_handoff(handoff_summary)
            result["handoff_summary"] = handoff_summary

        result["memory_items_stored"] = await cls.store_memory_items(
            delta=delta,
            session_id=session_id,
            diary_content=diary_content,
            handoff_summary=handoff_summary,
        )
        result["processed_message_count"] = len(delta.processed_keys)
        result["state_patch"] = cls._build_state_patch(state, delta)
        return result

    @classmethod
    def _normalize_transcript_messages(cls, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        visible: list[dict[str, Any]] = []
        has_epoch = False
        for msg in messages or []:
            if msg.get("role") not in ("user", "assistant"):
                continue
            if msg.get("source") in ("internal", "command_notice"):
                continue
            text = cls.message_text(msg)
            if not text:
                continue
            if "context_epoch" in msg:
                has_epoch = True
            visible.append({**msg, "content": text})
        if not visible:
            return []
        if not has_epoch:
            return visible
        newest_epoch = max(cls.message_context_epoch(msg) for msg in visible)
        return [msg for msg in visible if cls.message_context_epoch(msg) == newest_epoch]

    @classmethod
    def _select_delta(
        cls,
        messages: list[dict[str, Any]],
        session_id: str,
        state: dict[str, Any],
    ) -> IngestionDelta:
        context_epoch = max((cls.message_context_epoch(msg) for msg in messages), default=0)
        scope_key = f"{session_id}:epoch:{context_epoch}"
        memory_state = state.get("memory_ingestion") if isinstance(state.get("memory_ingestion"), dict) else {}
        processed_by_scope = (
            memory_state.get("processed_by_scope")
            if isinstance(memory_state.get("processed_by_scope"), dict)
            else {}
        )
        processed = set(processed_by_scope.get(scope_key) or [])

        delta_messages: list[dict[str, Any]] = []
        processed_keys: list[str] = []
        for index, msg in enumerate(messages):
            key = cls.message_key(msg, index=index)
            scoped_key = f"{scope_key}:{key}"
            if scoped_key in processed:
                continue
            delta_messages.append(msg)
            processed_keys.append(scoped_key)

        turn_key = cls._turn_key(delta_messages)
        marker_id = cls._stable_marker_id(scope_key, turn_key)
        return IngestionDelta(
            messages=delta_messages,
            context_epoch=context_epoch,
            scope_key=scope_key,
            turn_key=turn_key,
            marker_id=marker_id,
            processed_keys=processed_keys,
        )

    @classmethod
    def _build_state_patch(cls, state: dict[str, Any], delta: IngestionDelta) -> dict[str, Any]:
        memory_state = state.get("memory_ingestion") if isinstance(state.get("memory_ingestion"), dict) else {}
        processed_by_scope = (
            memory_state.get("processed_by_scope")
            if isinstance(memory_state.get("processed_by_scope"), dict)
            else {}
        )
        next_processed = list(dict.fromkeys([*(processed_by_scope.get(delta.scope_key) or []), *delta.processed_keys]))
        processed_by_scope[delta.scope_key] = next_processed[-_MAX_PROCESSED_KEYS:]

        scope_order = [str(s) for s in memory_state.get("scope_order", []) if s]
        if delta.scope_key in scope_order:
            scope_order.remove(delta.scope_key)
        scope_order.append(delta.scope_key)
        for stale_scope in scope_order[:-_MAX_TRACKED_SCOPES]:
            processed_by_scope.pop(stale_scope, None)
        scope_order = scope_order[-_MAX_TRACKED_SCOPES:]

        return {
            "memory_ingestion": {
                "processed_by_scope": processed_by_scope,
                "scope_order": scope_order,
                "updated_at": datetime.now().isoformat(),
            }
        }

    @classmethod
    def build_diary_delta(cls, messages: list[dict[str, Any]], *, session_id: str) -> str:
        lines = [f"Session: {session_id}"]
        for msg in messages:
            role = msg.get("role", "")
            text = cls._clean_text(cls.message_text(msg))
            if len(text) < 3:
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"- {label}: {cls.truncate(text, 240)}")
            if len("\n".join(lines)) >= _MAX_DIARY_CHARS:
                break
        if len(lines) <= 1:
            return ""
        content = "\n".join(lines)
        return cls.truncate(content, _MAX_DIARY_CHARS)

    @classmethod
    def build_session_handoff(cls, messages: list[dict[str, Any]], session_id: str) -> str:
        turns = [
            (msg.get("role", ""), cls._clean_text(cls.message_text(msg)))
            for msg in messages
            if msg.get("role") in ("user", "assistant") and len(cls.message_text(msg)) >= 3
        ]
        if not turns:
            return ""
        lines = [
            f"Session: {session_id}",
            "",
            "## Recent context",
        ]
        for role, text in turns[-_MAX_HANDOFF_TURNS:]:
            label = "User" if role == "user" else "Assistant"
            lines.append(f"- {label}: {cls.truncate(text, 220)}")
        todos = cls.scan_todos(messages)
        if todos:
            lines.extend(["", "## Pending TODOs"])
            lines.extend(f"- [ ] {todo}" for todo in todos[:5])
        return "\n".join(lines).strip()

    @staticmethod
    def write_session_handoff(summary: str) -> bool:
        path = AgentManager._personal_dir() / "session_handoff.md"
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# Session Handoff - {now}\n\n{summary}\n", encoding="utf-8")
            return True
        except OSError as exc:
            logger.warning("Memory ingestion: failed to write session handoff: %s", exc)
            return False

    @classmethod
    async def store_memory_items(
        cls,
        *,
        delta: IngestionDelta,
        session_id: str,
        diary_content: str,
        handoff_summary: str,
    ) -> int:
        from app.agents.memory_os import get_memory_os

        memory_os = get_memory_os()
        today = datetime.now().strftime("%Y-%m-%d")
        source_prefix = f"session_end:{today}:{session_id}:epoch:{delta.context_epoch}"
        stored = 0
        candidates: list[dict[str, Any]] = []

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
                "dedupe_key": f"heartbeat:{session_id}:{delta.context_epoch}:handoff",
                "canonical_key": f"working:handoff:{session_id}:{delta.context_epoch}",
            })

        if diary_content:
            candidates.append({
                "content": diary_content,
                "memory_type": "episodic",
                "source": "heartbeat",
                "source_ref": f"{source_prefix}:delta:{delta.marker_id}",
                "summary": "Automatic turn delta summary",
                "tier": "warm",
                "confidence": 0.68,
                "metadata": {
                    "auto_extracted": True,
                    "kind": "turn_delta",
                    "session_id": session_id,
                    "turn_key": delta.turn_key,
                },
                "dedupe_key": f"heartbeat:{session_id}:{delta.context_epoch}:delta:{delta.marker_id}",
                "canonical_key": f"episodic:turn_delta:{delta.marker_id}",
            })

        extracted = await cls.extract_memory_candidates(delta.messages, session_id=session_id)
        for idx, item in enumerate(extracted):
            candidates.append({
                "content": cls.truncate(item["content"], _MAX_MEMORY_CONTENT_CHARS),
                "memory_type": item["memory_type"],
                "source": "heartbeat",
                "source_ref": f"{source_prefix}:extracted:{delta.marker_id}:{idx}",
                "summary": item.get("summary") or "Extracted durable memory",
                "tier": item.get("tier") or ("hot" if item.get("explicit") else "warm"),
                "confidence": item["confidence"],
                "metadata": {
                    "auto_extracted": True,
                    "kind": "llm_extracted" if item.get("from_llm") else "rule_extracted",
                    "session_id": session_id,
                    "turn_key": delta.turn_key,
                    "entities": item.get("entities") or [],
                    "event_time": item.get("event_time") or "",
                    "ttl_hint": item.get("ttl_hint") or "",
                    "canonical_key": item.get("canonical_key") or "",
                },
                "dedupe_key": "",
                "canonical_key": item.get("canonical_key") or "",
            })

        for candidate in candidates[:10]:
            try:
                memory_os.upsert_item(created_by="heartbeat", **candidate)
                stored += 1
            except Exception as exc:
                logger.info("Memory ingestion skipped %s: %s", candidate.get("source_ref"), exc)
        return stored

    @classmethod
    async def extract_memory_candidates(
        cls,
        messages: list[dict[str, Any]],
        *,
        session_id: str,
    ) -> list[dict[str, Any]]:
        durable_texts = [
            cls.message_text(msg)
            for msg in messages
            if msg.get("role") == "user" and cls.is_durable_memory_candidate(cls.message_text(msg))
        ]
        if not durable_texts:
            return []

        llm_items: Optional[list[dict[str, Any]]] = None
        try:
            llm_items = await cls.extract_with_llm(durable_texts, session_id=session_id)
        except Exception as exc:
            logger.info("Memory extraction LLM skipped: %s", exc)
        if llm_items is not None:
            return cls._validate_extracted_items(llm_items, source_texts=durable_texts, from_llm=True)

        fallback: list[dict[str, Any]] = []
        for text in durable_texts:
            fallback.extend(cls._rule_based_items(text))
        return cls._validate_extracted_items(fallback, source_texts=durable_texts, from_llm=False)

    @classmethod
    async def extract_with_llm(cls, texts: list[str], *, session_id: str) -> Optional[list[dict[str, Any]]]:
        """Best-effort low-cost JSON extraction.

        Returning ``None`` means callers should use deterministic fallback rules.
        Returning an empty list means the extractor intentionally stored nothing.
        """
        if not texts:
            return []
        enabled = os.environ.get("DESKTOP_AGENT_MEMORY_LLM_EXTRACT", "1").strip().lower()
        if enabled in {"0", "false", "no", "off"} or os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        from app.config import get_model_for_agent
        from app.models import ModelRouter

        model_id = get_model_for_agent("personal")
        router = ModelRouter(model_id)
        payload = "\n".join(f"- {cls.truncate(t, 600)}" for t in texts[:8])
        system = (
            "Extract durable long-term memory from user messages. "
            "Return only JSON with an `items` array. Each item must have "
            "memory_type, content, confidence, canonical_key, entities, event_time, ttl_hint, skip_reason. "
            "Use memory_type one of working, episodic, semantic, procedural, identity. "
            "Skip secrets, API keys, passwords, vague speculation, and one-off chatter. "
            "Use identity only for explicit stable profile facts with confidence >= 0.9."
        )
        user = f"Session: {session_id}\nMessages:\n{payload}"
        response = await router.chat_completion_non_stream(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            tools=[],
            temperature=0.1,
            max_tokens=900,
            thinking_intensity="low",
        )
        text = str(
            (response.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        ).strip()
        if not text:
            return None
        parsed = cls._parse_json_object(text)
        if parsed is None:
            return None
        items = parsed.get("items")
        return items if isinstance(items, list) else []

    @classmethod
    def _validate_extracted_items(
        cls,
        items: Iterable[dict[str, Any]],
        *,
        source_texts: list[str],
        from_llm: bool,
    ) -> list[dict[str, Any]]:
        valid: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in items:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("skip_reason") or "").strip():
                continue
            content = cls._clean_text(str(raw.get("content") or ""))
            if not content or cls.contains_sensitive(content):
                continue
            memory_type = str(raw.get("memory_type") or "semantic")
            if memory_type not in {"working", "episodic", "semantic", "procedural", "identity"}:
                memory_type = "semantic"
            try:
                confidence = max(0.0, min(float(raw.get("confidence", 0.75)), 1.0))
            except (TypeError, ValueError):
                confidence = 0.75
            if confidence < _MIN_MEMORY_CONFIDENCE:
                continue
            if memory_type == "identity" and confidence < 0.9:
                continue
            canonical_key = cls._canonical_key(raw.get("canonical_key"), memory_type, content)
            key = canonical_key or cls._stable_marker_id(memory_type, content)
            if key in seen:
                continue
            seen.add(key)
            valid.append({
                "content": content,
                "summary": str(raw.get("summary") or "").strip(),
                "memory_type": memory_type,
                "confidence": confidence,
                "canonical_key": canonical_key,
                "entities": raw.get("entities") if isinstance(raw.get("entities"), list) else [],
                "event_time": str(raw.get("event_time") or "").strip(),
                "ttl_hint": str(raw.get("ttl_hint") or "").strip(),
                "tier": str(raw.get("tier") or "").strip(),
                "explicit": any(cls.is_explicit_remember(text) for text in source_texts),
                "from_llm": from_llm,
            })
        return valid

    @classmethod
    def _rule_based_items(cls, text: str) -> list[dict[str, Any]]:
        clean = cls._strip_remember_prefix(cls._clean_text(text))
        memory_type = "semantic"
        summary = "User-stated durable preference or decision"
        if re.search(r"(怎么做|流程|步骤|workflow|procedure|下次.*先|以后.*先)", clean, re.IGNORECASE):
            memory_type = "procedural"
            summary = "Reusable workflow or correction"
        elif re.search(r"(今天|昨天|明天|刚才|本次|这次|session|会话)", clean, re.IGNORECASE):
            memory_type = "episodic"
            summary = "Dated conversation event"
        confidence = 0.86 if cls.is_explicit_remember(text) else 0.76
        return [{
            "content": clean,
            "summary": summary,
            "memory_type": memory_type,
            "confidence": confidence,
            "canonical_key": cls._canonical_key("", memory_type, clean),
            "entities": [],
            "event_time": "",
            "ttl_hint": "",
            "tier": "hot" if cls.is_explicit_remember(text) else "warm",
        }]

    @classmethod
    def is_durable_memory_candidate(cls, text: str) -> bool:
        clean = str(text or "").strip()
        if len(clean) < 12:
            return False
        if cls.contains_sensitive(clean):
            return False
        if cls._looks_like_mojibake_remember(clean):
            return True
        return any(re.search(pattern, clean, re.IGNORECASE) for pattern in _DURABLE_MEMORY_PATTERNS)

    @classmethod
    def contains_sensitive(cls, text: str) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in _SENSITIVE_MEMORY_PATTERNS)

    @classmethod
    def is_explicit_remember(cls, text: str) -> bool:
        return cls._looks_like_mojibake_remember(text or "") or bool(
            re.search(_DURABLE_MEMORY_PATTERNS[0], text or "", re.IGNORECASE)
        )

    @staticmethod
    def _looks_like_mojibake_remember(text: str) -> bool:
        # Some historical tests/runtime files contain UTF-8 Chinese decoded as
        # Windows-1252 twice. Treat that as a valid explicit remember signal so
        # the ingestion path remains robust during migration.
        if "Ã" in text and "Â" in text and ("Â°" in text or "Å¡" in text):
            return True
        return "è¯" in text and "è®" in text

    @classmethod
    def scan_todos(cls, messages: list[dict[str, Any]]) -> list[str]:
        patterns = [
            r"(我会|我来|我帮你|稍后|接下来|等一下|回头)",
            r"(TODO|todo|FIXME|fixme|HACK|hack)",
            r"(还没|尚未|有待|待做|待办)",
        ]
        todos: list[str] = []
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = cls.message_text(msg)
            for pattern in patterns:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    start = max(0, match.start() - 20)
                    end = min(len(content), match.end() + 80)
                    line = cls._clean_text(content[start:end])
                    if line and line not in todos:
                        todos.append(cls.truncate(line, 200))
        return todos[:10]

    @staticmethod
    def message_text(msg: dict[str, Any]) -> str:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
        return str(content).strip()

    @staticmethod
    def message_context_epoch(msg: dict[str, Any]) -> int:
        try:
            return int(msg.get("context_epoch") or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def message_key(cls, msg: dict[str, Any], *, index: int) -> str:
        for field in ("message_id", "id"):
            value = str(msg.get(field) or "").strip()
            if value:
                return value
        turn = str(msg.get("turn_id") or "").strip()
        content = cls._clean_text(cls.message_text(msg))
        digest = uuid.uuid5(uuid.NAMESPACE_URL, f"{msg.get('role')}:{index}:{content}").hex[:16]
        return f"{turn or 'idx-' + str(index)}:{digest}"

    @classmethod
    def _turn_key(cls, messages: list[dict[str, Any]]) -> str:
        turn_ids = [str(msg.get("turn_id") or "").strip() for msg in messages if msg.get("turn_id")]
        if turn_ids:
            return turn_ids[-1]
        joined = "\n".join(f"{msg.get('role')}:{cls.message_text(msg)}" for msg in messages)
        return cls._stable_marker_id("turn", joined)

    @staticmethod
    def _stable_marker_id(*parts: str) -> str:
        raw = "\n".join(str(p) for p in parts)
        return uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:16]

    @staticmethod
    def _parse_json_object(text: str) -> Optional[dict[str, Any]]:
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _canonical_key(value: Any, memory_type: str, content: str) -> str:
        explicit = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if explicit:
            return explicit[:180]
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        normalized = re.sub(r"^(请记住|帮我记住|记住一下|remember this|please remember)[:：\s]*", "", normalized)
        return f"{memory_type}:{normalized[:140]}"

    @staticmethod
    def _strip_remember_prefix(text: str) -> str:
        return re.sub(
            r"^(请记住|帮我记住|记住一下|以后记得|remember this|please remember)[:：,\s]*",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        ).strip()

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip())

    @staticmethod
    def truncate(text: str, max_chars: int) -> str:
        compact = re.sub(r"\s+", " ", str(text or "").strip())
        if len(compact) <= max_chars:
            return compact
        return compact[: max_chars - 1].rstrip() + "..."

    @staticmethod
    def state_updated_at() -> str:
        return datetime.fromtimestamp(time.time()).isoformat()
