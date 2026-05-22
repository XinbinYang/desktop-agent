"""Tests for the gateway translator layer (Discord + Feishu).

The translators are mocked end-to-end: we feed them the same event
sequence ``SessionRuntime`` would broadcast and assert that the platform
APIs receive the expected calls.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.gateway.translators.base import Translator
from app.gateway.translators.discord import DiscordTranslator
from app.gateway.translators.feishu import FeishuCardTranslator


# ── Fakes ───────────────────────────────────────────────────────────


class FakeDiscordMessage:
    _ids = 0

    def __init__(self, content: str = ""):
        FakeDiscordMessage._ids += 1
        self.id = FakeDiscordMessage._ids
        self.content = content
        self.edits: List[str] = []

    async def edit(self, *, content: str, **_: Any) -> None:
        self.content = content
        self.edits.append(content)


class _FakeTyping:
    """Async-context-manager mock for discord.py's ``channel.typing()``."""

    def __init__(self, channel: "FakeDiscordChannel") -> None:
        self._channel = channel

    async def __aenter__(self) -> "_FakeTyping":
        self._channel.typing_started += 1
        self._channel.typing_active = True
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        self._channel.typing_active = False
        return False


class FakeDiscordChannel:
    def __init__(self) -> None:
        self.sent: List[FakeDiscordMessage] = []
        self.embeds: List[Any] = []
        self.typing_started = 0
        self.typing_active = False

    def typing(self) -> "_FakeTyping":
        return _FakeTyping(self)

    async def send(self, content: str = "", *, embed: Any = None, **_: Any) -> FakeDiscordMessage:
        if embed is not None:
            self.embeds.append(embed)
        msg = FakeDiscordMessage(content=content)
        self.sent.append(msg)
        return msg


class FakeResponse:
    def __init__(self, ok: bool = True, message_id: str = "msg-1") -> None:
        self._ok = ok
        self.data = type("Data", (), {"message_id": message_id})()
        self.code = 0 if ok else 1
        self.msg = "" if ok else "fake-error"

    def success(self) -> bool:
        return self._ok


class FakeFeishuClient:
    def __init__(self, *, card_ok: bool = True, patch_ok: bool = True) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._card_ok = card_ok
        self._patch_ok = patch_ok
        self._create_calls = 0

        class _MsgAPI:
            outer = self

            def create(self_inner, req):  # noqa: D401
                self.calls.append({"op": "create", "req": req})
                self._create_calls += 1
                return FakeResponse(ok=self._card_ok if self._create_calls == 1 else True)

            def patch(self_inner, req):
                self.calls.append({"op": "patch", "req": req})
                return FakeResponse(ok=self._patch_ok)

            def update(self_inner, req):
                self.calls.append({"op": "update", "req": req})
                return FakeResponse(ok=True)

        class _V1:
            message = _MsgAPI()

        class _Im:
            v1 = _V1()

        self.im = _Im()


# ── Helpers ─────────────────────────────────────────────────────────


async def _drive(translator: Translator, events: List[Dict[str, Any]]) -> None:
    for ev in events:
        await translator.handle_event(ev)


def _content(text: str) -> Dict[str, Any]:
    return {"type": "content", "data": {"text": text}}


def _done() -> Dict[str, Any]:
    return {"type": "done"}


def _completed() -> Dict[str, Any]:
    return {"type": "run_completed", "data": {"status": "completed"}}


def _tool(name: str, **fields: Any) -> Dict[str, Any]:
    data = {"name": name, "args": {}, "result": "", "duration_ms": 12.0}
    data.update(fields)
    return {"type": "tool_call", "data": data}


# ── Discord ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_placeholder_streams_then_finalizes():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)
    translator._min_flush_chars = 1  # flush every event for determinism
    translator._min_flush_interval = 0

    await _drive(translator, [
        _content("Hello"),
        _content(", world!"),
        _completed(),
        _done(),
    ])

    # First content created the streaming message, then edited it to final.
    assert len(channel.sent) == 1
    placeholder = channel.sent[0]
    assert placeholder.content.endswith("Hello, world!")
    assert any("Hello" in edit for edit in placeholder.edits)
    # Native typing indicator is not left running after completion.
    assert channel.typing_active is False


@pytest.mark.asyncio
async def test_discord_tool_call_is_silent_by_default():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    await _drive(translator, [
        _content("Looking up files"),
        _tool("file_read", args={"path": "README.md"}, result="ok", duration_ms=50),
        _content(" - done."),
        _done(),
    ])

    assert channel.embeds == []
    assert len(channel.sent) == 1
    assert channel.sent[0].content.endswith("Looking up files - done.")


@pytest.mark.asyncio
async def test_discord_tool_call_emits_embed_in_debug_mode():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel, tool_visibility="debug")
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    pytest.importorskip("discord")

    await _drive(translator, [
        _content("Looking up files"),
        _tool("file_read", args={"path": "README.md"}, result="ok", duration_ms=50),
        _content(" - done."),
        _done(),
    ])

    assert len(channel.embeds) == 1
    embed = channel.embeds[0]
    assert "file_read" in embed.title


@pytest.mark.asyncio
async def test_discord_long_output_splits_into_continuation_messages():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    huge = "x" * 5000
    await _drive(translator, [_content(huge), _done()])

    # 1 placeholder + at least 1 continuation message
    assert len(channel.sent) >= 2


@pytest.mark.asyncio
async def test_discord_error_renders_without_placeholder():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)

    await translator.handle_event({"type": "error", "data": {"message": "boom"}})

    assert channel.sent
    assert "boom" in channel.sent[0].content
    assert channel.typing_active is False


@pytest.mark.asyncio
async def test_discord_typing_starts_on_on_start():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)

    await translator.on_start()
    await asyncio.sleep(0)  # let the typing task enter the indicator

    # Native typing indicator is shown; no literal "Thinking..." message.
    assert channel.typing_started == 1
    assert channel.typing_active is True
    assert channel.sent == []

    await translator._stop_typing()  # cleanup the background task
    assert channel.typing_active is False


@pytest.mark.asyncio
async def test_discord_typing_stops_when_content_arrives():
    channel = FakeDiscordChannel()
    translator = DiscordTranslator(channel)
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    # A status event triggers on_start without content; yield so the typing
    # task actually enters the indicator before the first token arrives.
    await translator.handle_event({"type": "status", "data": {"status": "thinking"}})
    await asyncio.sleep(0)
    assert channel.typing_active is True

    await _drive(translator, [_content("Hi"), _done()])

    # First content stops the indicator and posts a real streaming message.
    assert channel.typing_started == 1
    assert channel.typing_active is False
    assert len(channel.sent) == 1
    assert channel.sent[0].content.endswith("Hi")


# ── Feishu ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_feishu_card_path_creates_and_patches():
    client = FakeFeishuClient(card_ok=True, patch_ok=True)
    translator = FeishuCardTranslator(client, chat_id="chat-1", root_id="root-1")
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    pytest.importorskip("lark_oapi")

    await _drive(translator, [
        _content("Hello"),
        _content(" world"),
        _completed(),
        _done(),
    ])

    ops = [c["op"] for c in client.calls]
    assert ops[0] == "create"
    assert "patch" in ops
    # No fallback to plain text
    assert "update" not in ops


@pytest.mark.asyncio
async def test_feishu_tool_call_is_silent_by_default():
    client = FakeFeishuClient(card_ok=True, patch_ok=True)
    translator = FeishuCardTranslator(client, chat_id="chat-1", root_id="root-1")

    await _drive(translator, [
        _tool("file_read", args={"path": "README.md"}, result="ok", duration_ms=50),
        _done(),
    ])

    assert translator._tool_sections == []


@pytest.mark.asyncio
async def test_feishu_tool_call_adds_section_in_debug_mode():
    client = FakeFeishuClient(card_ok=True, patch_ok=True)
    translator = FeishuCardTranslator(
        client,
        chat_id="chat-1",
        root_id="root-1",
        tool_visibility="debug",
    )

    await _drive(translator, [
        _tool("file_read", args={"path": "README.md"}, result="ok", duration_ms=50),
        _done(),
    ])

    assert len(translator._tool_sections) == 1
    assert "file_read" in translator._tool_sections[0]["text"]["content"]


@pytest.mark.asyncio
async def test_feishu_falls_back_to_text_when_card_creation_fails():
    client = FakeFeishuClient(card_ok=False)
    translator = FeishuCardTranslator(client, chat_id="chat-1")
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    pytest.importorskip("lark_oapi")

    await _drive(translator, [
        _content("Hello"),
        _done(),
    ])

    ops = [c["op"] for c in client.calls]
    # Two `create` attempts (card → text fallback) then `update` on flush.
    assert ops.count("create") == 2
    assert "update" in ops


@pytest.mark.asyncio
async def test_feishu_falls_back_mid_stream_when_patch_fails():
    client = FakeFeishuClient(card_ok=True, patch_ok=False)
    translator = FeishuCardTranslator(client, chat_id="chat-1")
    translator._min_flush_chars = 1
    translator._min_flush_interval = 0

    pytest.importorskip("lark_oapi")

    await _drive(translator, [
        _content("Hello"),
        _done(),
    ])

    ops = [c["op"] for c in client.calls]
    assert ops[0] == "create"
    assert "update" in ops  # degraded to text edit
    assert translator._fallback_text_mode is True
