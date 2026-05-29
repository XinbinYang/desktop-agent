from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any, List, Optional

from app.gateway.formatting import clean_text, split_for_discord, truncate
from app.gateway.translators.base import ToolCall, Translator

logger = logging.getLogger(__name__)


_DISCORD_LIMIT = 2000
_EDIT_LIMIT = 1900  # leave room for continuation marker


class DiscordTranslator(Translator):
    """Native-typing-indicator translator for Discord.

    While the agent works, Discord's native typing indicator is shown. On the
    first content, a streaming message is posted and edited as tokens arrive.
    When the buffer exceeds Discord's 2000-char limit, the message is sealed
    with a "(continued ⤵)" marker and the remainder streams into a fresh
    message that becomes the new placeholder. Tool calls are silent by default
    and only render as standalone embeds when tool_visibility="debug".
    """

    def __init__(
        self,
        channel: Any,
        *,
        reply_to: Any = None,
        placeholder_text: str = "Thinking...",
        tool_visibility: str = "silent",
    ) -> None:
        super().__init__(tool_visibility=tool_visibility)
        self._channel = channel
        self._reply_to = reply_to
        self._placeholder_text = placeholder_text
        self._placeholder: Any = None
        self._sealed_messages: List[Any] = []
        self._render_lock = asyncio.Lock()
        self._typing_task: Optional[asyncio.Task] = None

    async def on_start(self) -> None:
        # Show Discord's native typing indicator instead of posting a literal
        # "Thinking..." message. The first real content render stops it and
        # replaces it with a streaming message (see _render_partial).
        if getattr(self._channel, "typing", None) is not None:
            self._typing_task = asyncio.create_task(self._run_typing())

    async def _run_typing(self) -> None:
        try:
            async with self._channel.typing():
                # discord.py auto-refreshes the typing request ~every 5s while
                # inside this context manager; hold it open until cancelled.
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("[discord] typing indicator failed", exc_info=True)

    async def _stop_typing(self) -> None:
        task = self._typing_task
        if task is None:
            return
        self._typing_task = None
        if not task.done():
            task.cancel()
        # CancelledError is a BaseException; suppress(Exception) alone misses it.
        with suppress(asyncio.CancelledError, Exception):
            await task

    async def on_tool_call(self, tool: ToolCall) -> None:
        try:
            import discord  # type: ignore
        except ImportError:
            return
        try:
            embed = discord.Embed(title=f"🔧 {tool.name or 'tool'}", color=0x5865F2)
            if tool.args:
                args_str = ", ".join(
                    f"{k}={truncate(str(v), 100)}" for k, v in tool.args.items()
                )
                embed.add_field(name="Args", value=truncate(args_str, 800), inline=False)
            if tool.result:
                embed.add_field(
                    name="Result", value=truncate(str(tool.result), 800), inline=False,
                )
            if tool.duration_ms:
                embed.set_footer(text=f"{tool.duration_ms / 1000:.1f}s")
            with suppress(Exception):
                await self._channel.send(embed=embed)
        except Exception:
            logger.debug("[discord] tool embed failed", exc_info=True)

    async def on_error(self, exc: BaseException) -> None:
        await self._stop_typing()
        text = f"⚠️ {type(exc).__name__}: {exc}" if str(exc) else f"⚠️ {type(exc).__name__}"
        if self._placeholder is not None:
            with suppress(Exception):
                await self._edit(self._placeholder, text[:_DISCORD_LIMIT])
                return
        with suppress(Exception):
            await self._send_text(text[:_DISCORD_LIMIT])

    async def on_complete(self, full_text: str, *, status: str) -> None:
        await self._stop_typing()
        # Final flush already happened in _flush(force=True); ensure something
        # was sent if the agent produced no content at all.
        if not full_text.strip():
            with suppress(Exception):
                if self._placeholder is not None:
                    await self._edit(self._placeholder, "_(Agent completed without text)_")
                else:
                    await self._send_text("_(Agent completed without text)_")

    async def _render_partial(self, text: str, *, final: bool) -> None:
        text = clean_text(text)
        if not text:
            return
        # First real content: drop the native typing indicator before posting.
        await self._stop_typing()
        async with self._render_lock:
            chunks = split_for_discord(text, limit=_EDIT_LIMIT)
            # First chunk goes into the active placeholder (edit), subsequent
            # chunks become new messages, the last of which becomes the new
            # placeholder so future tokens keep streaming.
            for index, chunk in enumerate(chunks):
                is_last = index == len(chunks) - 1
                display = chunk if is_last else chunk + "\n\n_(continued ⤵)_"
                if self._placeholder is None:
                    self._placeholder = await self._send_text(display)
                    continue
                if index == 0:
                    await self._edit(self._placeholder, display)
                    if not is_last:
                        # Seal current placeholder, open next.
                        self._sealed_messages.append(self._placeholder)
                        self._placeholder = None
                else:
                    msg = await self._send_text(display)
                    if is_last:
                        self._placeholder = msg
                    else:
                        self._sealed_messages.append(msg)

    async def _send_text(self, content: str, *, reply: Any = None) -> Any:
        kwargs = {}
        try:
            import discord  # type: ignore
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        except ImportError:
            pass
        if reply is not None:
            try:
                return await self._channel.send(content, reference=reply, **kwargs)
            except TypeError:
                pass
        try:
            return await self._channel.send(content, **kwargs)
        except TypeError:
            return await self._channel.send(content)

    async def _edit(self, message: Any, content: str) -> None:
        kwargs: dict = {"content": content}
        try:
            import discord  # type: ignore
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        except ImportError:
            pass
        try:
            await message.edit(**kwargs)
        except TypeError:
            await message.edit(content=content)
