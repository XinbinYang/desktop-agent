from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ToolCall:
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    result: str = ""
    duration_ms: float = 0.0
    tool_call_id: str = ""


class Translator(ABC):
    """Render SessionRuntime events onto a platform.

    The runner feeds raw agent events to ``handle_event``; the default
    implementation classifies them and dispatches to high-level hooks
    (``on_start``, ``on_token``, ``on_tool_call``, ``on_status``,
    ``on_complete``, ``on_error``).

    Translators accumulate text into ``buffer`` and flush at a throttled
    cadence to avoid hammering platform APIs (Discord/Feishu rate limits).
    Concrete subclasses implement ``_render_partial`` and ``_render_final``.
    """

    DEFAULT_MIN_FLUSH_CHARS = 120
    DEFAULT_MIN_FLUSH_INTERVAL = 0.8
    TOOL_VISIBILITY_OPTIONS = {"silent", "debug"}

    def __init__(
        self,
        *,
        min_flush_chars: int = DEFAULT_MIN_FLUSH_CHARS,
        min_flush_interval: float = DEFAULT_MIN_FLUSH_INTERVAL,
        tool_visibility: str = "silent",
    ) -> None:
        self.buffer: str = ""
        self._last_flush_at: float = 0.0
        self._min_flush_chars = min_flush_chars
        self._min_flush_interval = min_flush_interval
        self._tool_visibility = self._normalize_tool_visibility(tool_visibility)
        self._lock = asyncio.Lock()
        self._started = False
        self._completed = False

    async def handle_event(self, event: Dict[str, Any]) -> None:
        etype = event.get("type") or ""
        data = event.get("data") if isinstance(event.get("data"), dict) else {}

        if not self._started:
            self._started = True
            await self.on_start()

        if etype == "content":
            text = str(data.get("text", "") or "")
            if text:
                self.buffer += text
                await self._maybe_flush()
        elif etype == "tool_call":
            await self._maybe_render_tool_call(data)
        elif etype == "worker_tool_call":
            await self._maybe_render_tool_call(data)
        elif etype == "status":
            status = str(data.get("status", "") or "")
            if status:
                await self.on_status(status)
        elif etype == "interrupted":
            await self.on_error(asyncio.CancelledError(data.get("message", "cancelled")))
        elif etype == "error":
            message = str(data.get("message", "") or "Unknown error")
            await self.on_error(RuntimeError(message))
        elif etype == "run_completed":
            await self._finalize(status=str(data.get("status") or "completed"))
        elif etype == "done":
            await self._finalize(status="completed")

    async def _finalize(self, status: str) -> None:
        if self._completed:
            return
        self._completed = True
        await self._flush(force=True)
        await self.on_complete(self.buffer, status=status)

    async def _maybe_flush(self) -> None:
        now = time.monotonic()
        delta_chars = len(self.buffer)
        delta_time = now - self._last_flush_at
        if delta_chars >= self._min_flush_chars or delta_time >= self._min_flush_interval:
            await self._flush(force=False)

    async def _flush(self, *, force: bool) -> None:
        async with self._lock:
            if not self.buffer:
                return
            self._last_flush_at = time.monotonic()
            try:
                await self._render_partial(self.buffer, final=force)
            except Exception:
                # never let render failure kill the event loop;
                # subclasses log inside their render methods.
                pass

    @staticmethod
    def _coerce_tool(data: Dict[str, Any]) -> ToolCall:
        return ToolCall(
            name=str(data.get("name", "") or ""),
            args=data.get("args") if isinstance(data.get("args"), dict) else {},
            result=str(data.get("result", "") or ""),
            duration_ms=float(data.get("duration_ms", 0) or 0),
            tool_call_id=str(data.get("tool_call_id", "") or ""),
        )

    @classmethod
    def _normalize_tool_visibility(cls, value: str) -> str:
        visibility = str(value or "silent").strip().lower()
        return visibility if visibility in cls.TOOL_VISIBILITY_OPTIONS else "silent"

    async def _maybe_render_tool_call(self, data: Dict[str, Any]) -> None:
        if self._tool_visibility != "debug":
            return
        await self.on_tool_call(self._coerce_tool(data))

    # ── Hooks for subclasses ────────────────────────────────────────

    async def on_start(self) -> None:
        """Called once before the first event."""
        return None

    async def on_status(self, status: str) -> None:
        """High-level agent status (thinking/completed/...)."""
        return None

    async def on_tool_call(self, tool: ToolCall) -> None:
        """A tool call was executed."""
        return None

    async def on_error(self, exc: BaseException) -> None:
        """The agent failed or was cancelled."""
        return None

    async def on_complete(self, full_text: str, *, status: str) -> None:
        """The turn finished. ``full_text`` is the accumulated buffer."""
        return None

    @abstractmethod
    async def _render_partial(self, text: str, *, final: bool) -> None:
        """Render the current accumulated buffer to the platform."""
        ...
