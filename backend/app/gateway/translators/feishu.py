from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any, Dict, List, Optional

from app.gateway.formatting import clean_text, truncate
from app.gateway.translators.base import ToolCall, Translator

logger = logging.getLogger(__name__)


_FEISHU_TEXT_LIMIT = 3000  # per element fallback budget
_CARD_BODY_LIMIT = 28000  # Feishu rich-text element soft cap


class FeishuCardTranslator(Translator):
    """Streams an Interactive Card on Feishu/Lark.

    Layout:
        ┌─ header: "Desktop Agent — <status>"
        ├─ markdown(streaming body)
        ├─ note(elapsed/iteration)
        └─ tool sections only when tool_visibility="debug"

    The card is created when ``on_start`` fires and patched on every flush.
    If the card endpoint fails (permission / API outage), the translator
    falls back to plain-text message editing using the same root message
    id so the conversation does not break.
    """

    def __init__(
        self,
        api_client: Any,
        *,
        chat_id: str,
        root_id: str = "",
        title: str = "Desktop Agent",
        tool_visibility: str = "silent",
    ) -> None:
        super().__init__(tool_visibility=tool_visibility)
        self._api = api_client
        self._chat_id = chat_id
        self._root_id = root_id
        self._title = title
        self._message_id: str = ""
        self._fallback_text_mode = False
        self._status_text = "thinking…"
        self._tool_sections: List[Dict[str, Any]] = []
        self._render_lock = asyncio.Lock()

    async def on_start(self) -> None:
        card = self._build_card(body="_Connecting…_")
        ok, mid = await asyncio.to_thread(self._create_card_message, card)
        if ok and mid:
            self._message_id = mid
            return
        # Card failed — fall back to plain text from the start.
        self._fallback_text_mode = True
        ok, mid = await asyncio.to_thread(self._create_text_message, "Thinking...")
        if ok:
            self._message_id = mid

    async def on_status(self, status: str) -> None:
        self._status_text = status
        await self._flush(force=False)

    async def on_tool_call(self, tool: ToolCall) -> None:
        section = {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": self._format_tool_markdown(tool),
            },
        }
        self._tool_sections.append(section)
        await self._flush(force=False)

    async def on_error(self, exc: BaseException) -> None:
        message = f"⚠️ {type(exc).__name__}: {exc}" if str(exc) else f"⚠️ {type(exc).__name__}"
        if not self._message_id:
            return
        if self._fallback_text_mode:
            await asyncio.to_thread(
                self._update_text_message, self._message_id, message[:_FEISHU_TEXT_LIMIT],
            )
        else:
            self._status_text = "error"
            await self._patch_card(body=message[:_CARD_BODY_LIMIT], finalized=True)

    async def on_complete(self, full_text: str, *, status: str) -> None:
        if not full_text.strip() and self._message_id:
            with suppress(Exception):
                if self._fallback_text_mode:
                    await asyncio.to_thread(
                        self._update_text_message,
                        self._message_id,
                        "_(Agent completed without text)_",
                    )
                else:
                    await self._patch_card(
                        body="_(Agent completed without text)_", finalized=True,
                    )
            return
        self._status_text = status
        await self._flush(force=True, finalized=True)

    async def _render_partial(self, text: str, *, final: bool) -> None:
        text = clean_text(text)
        if not text or not self._message_id:
            return
        async with self._render_lock:
            body = truncate(text, _CARD_BODY_LIMIT, suffix="\n…\n_(truncated)_")
            if self._fallback_text_mode:
                await asyncio.to_thread(
                    self._update_text_message, self._message_id, body[:_FEISHU_TEXT_LIMIT],
                )
                return
            ok = await self._patch_card(body=body, finalized=final)
            if not ok:
                # Card endpoint stopped working mid-stream — degrade to text.
                self._fallback_text_mode = True
                with suppress(Exception):
                    await asyncio.to_thread(
                        self._update_text_message,
                        self._message_id,
                        body[:_FEISHU_TEXT_LIMIT],
                    )

    async def _flush(self, *, force: bool, finalized: bool = False) -> None:
        # Reuse base flush so buffer+throttling stay consistent.
        await self._render_partial(self.buffer, final=finalized or force)

    # ── Card construction ───────────────────────────────────────────

    def _build_card(self, *, body: str, finalized: bool = False) -> Dict[str, Any]:
        elements: List[Dict[str, Any]] = [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": body or "_(empty)_"},
            }
        ]
        elements.extend(self._tool_sections)
        elements.append({
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": f"status: {self._status_text}"}
            ],
        })
        return {
            "config": {"wide_screen_mode": True, "update_multi": True},
            "header": {
                "title": {"tag": "plain_text", "content": self._title},
                "template": "green" if finalized else "blue",
            },
            "elements": elements,
        }

    def _format_tool_markdown(self, tool: ToolCall) -> str:
        lines = [f"**🔧 {tool.name or 'tool'}**"]
        if tool.args:
            args_preview = ", ".join(
                f"`{k}`={truncate(str(v), 80)}" for k, v in tool.args.items()
            )
            lines.append(f"_args:_ {truncate(args_preview, 600)}")
        if tool.result:
            lines.append(f"_result:_ {truncate(str(tool.result), 600)}")
        if tool.duration_ms:
            lines.append(f"_took {tool.duration_ms / 1000:.1f}s_")
        return "\n".join(lines)

    # ── Lark API thin wrappers (sync; called via to_thread) ─────────

    async def _patch_card(self, *, body: str, finalized: bool = False) -> bool:
        if not self._api or not self._message_id:
            return False
        card = self._build_card(body=body, finalized=finalized)
        return await asyncio.to_thread(self._patch_card_sync, card)

    def _patch_card_sync(self, card: Dict[str, Any]) -> bool:
        try:
            from lark_oapi.api.im.v1 import (
                PatchMessageRequest,
                PatchMessageRequestBody,
            )
            body = (
                PatchMessageRequestBody.builder()
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            )
            req = (
                PatchMessageRequest.builder()
                .message_id(self._message_id)
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.patch(req)
            if not resp.success():
                logger.debug(
                    "[feishu] patch card failed code=%s msg=%s",
                    getattr(resp, "code", "?"), getattr(resp, "msg", "?"),
                )
                return False
            return True
        except Exception as exc:
            logger.debug("[feishu] patch card error: %s", exc)
            return False

    def _create_card_message(self, card: Dict[str, Any]) -> tuple[bool, str]:
        if not self._api:
            return False, ""
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )
            payload_body = (
                CreateMessageRequestBody.builder()
                .receive_id(self._chat_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
            )
            if self._root_id:
                with suppress(Exception):
                    payload_body = payload_body.reply_in_thread(False)
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(payload_body.build())
                .build()
            )
            resp = self._api.im.v1.message.create(req)
            if not resp.success():
                logger.debug(
                    "[feishu] create card failed code=%s msg=%s",
                    getattr(resp, "code", "?"), getattr(resp, "msg", "?"),
                )
                return False, ""
            mid = getattr(getattr(resp, "data", None), "message_id", "") or ""
            return bool(mid), mid
        except Exception as exc:
            logger.debug("[feishu] create card error: %s", exc)
            return False, ""

    def _create_text_message(self, text: str) -> tuple[bool, str]:
        if not self._api:
            return False, ""
        try:
            from lark_oapi.api.im.v1 import (
                CreateMessageRequest,
                CreateMessageRequestBody,
            )
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(self._chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            req = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.create(req)
            if not resp.success():
                return False, ""
            mid = getattr(getattr(resp, "data", None), "message_id", "") or ""
            return bool(mid), mid
        except Exception:
            return False, ""

    def _update_text_message(self, message_id: str, text: str) -> bool:
        if not self._api or not message_id:
            return False
        try:
            from lark_oapi.api.im.v1 import (
                UpdateMessageRequest,
                UpdateMessageRequestBody,
            )
            body = (
                UpdateMessageRequestBody.builder()
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            req = (
                UpdateMessageRequest.builder()
                .message_id(message_id)
                .request_body(body)
                .build()
            )
            resp = self._api.im.v1.message.update(req)
            return resp.success()
        except Exception:
            return False
