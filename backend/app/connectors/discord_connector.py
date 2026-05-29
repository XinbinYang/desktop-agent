import asyncio
import logging
import time
from contextlib import suppress
from datetime import timezone
from typing import Any, Dict, Optional

from app.connectors.base import (
    ConnectorConfig,
    PlatformConnector,
    target_agent_config_schema,
    tool_visibility_config_schema,
)

logger = logging.getLogger(__name__)


class DiscordConnector(PlatformConnector):
    name = "discord"
    display_name = "Discord"
    description = "通过 Discord Bot 远程与 Agent 对话，支持 DM 和 @提及触发。"

    _STARTUP_TIMEOUT = 60
    _AGENT_RUN_TIMEOUT = 180

    def __init__(self, config: Optional[ConnectorConfig] = None):
        super().__init__(config)
        self._status = "stopped"
        self._status_message = ""
        self._client = None
        self._bot_task: Optional[asyncio.Task] = None
        self._ready_event: Optional[asyncio.Event] = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def status_message(self) -> str:
        return self._status_message

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "bot_token": {
                    "type": "string",
                    "label": "Bot Token",
                    "description": "Discord Developer Portal Bot Token",
                    "sensitive": True,
                },
                "target_agent": target_agent_config_schema(),
                "tool_visibility": tool_visibility_config_schema(),
                "notifications_enabled": {
                    "type": "boolean",
                    "label": "Enable Notifications",
                    "description": "Allow Desktop Agent to send proactive Discord notifications",
                    "default": False,
                },
                "notification_channel_id": {
                    "type": "string",
                    "label": "Notification Channel ID",
                    "description": "Discord channel or DM ID used by the test-message endpoint",
                },
                "request_message_content_intent": {
                    "type": "boolean",
                    "label": "Request Message Content Intent",
                    "description": "Only enable this when the Discord Developer Portal has Message Content Intent enabled. DM and @mention messages work without it.",
                    "default": False,
                },
            },
            "required": ["bot_token"],
        }

    async def health_check(self) -> Dict[str, Any]:
        healthy = self._status == "running"
        latency = None
        if self._client and hasattr(self._client, "latency"):
            lat = self._client.latency
            if lat:
                latency = round(lat * 1000, 1)
        if self._client and hasattr(self._client, "is_ready"):
            healthy = healthy and self._client.is_ready()
        details = self._status_message
        if self._last_error:
            details = f"{details} | last_error={self._last_error}" if details else self._last_error
        return {"healthy": healthy, "latency_ms": latency, "details": details}

    async def doctor(self) -> Dict[str, Any]:
        data = await super().doctor()
        data["dependencies"] = {"discord.py": self._dependency_available("discord")}
        if not data["dependencies"]["discord.py"]:
            data["recommendations"].append(
                r"Install Discord support: backend\\venv\\Scripts\\python.exe -m pip install discord.py"
            )
        data["recommendations"].extend([
            "Enable Message Content Intent in Discord Developer Portal if guild messages arrive empty.",
            "Leave Request Message Content Intent off unless Discord has explicitly enabled it for this bot.",
            "Invite the bot with View Channel, Send Messages, and Read Message History permissions.",
            "Use a numeric Discord channel ID for Notification Channel ID.",
        ])
        return data

    def _dependency_available(self, module_name: str) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    def _discord_exception_message(self, exc: BaseException) -> str:
        name = exc.__class__.__name__
        text = str(exc)
        if name == "LoginFailure":
            return f"Discord token is invalid: {text}"
        if "PrivilegedIntentsRequired" in name or "4014" in text:
            return (
                "Discord rejected a privileged intent. Enable Message Content Intent "
                "in the Developer Portal, then restart the connector."
            )
        return f"Discord connector error: {text or name}"

    async def _send_text(self, channel: Any, content: str):
        kwargs: Dict[str, Any] = {}
        try:
            import discord
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        except Exception:
            pass
        try:
            return await channel.send(content, **kwargs)
        except TypeError:
            return await channel.send(content)

    async def _edit_text(self, message: Any, content: str) -> None:
        kwargs: Dict[str, Any] = {"content": content}
        try:
            import discord
            kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        except Exception:
            pass
        try:
            await message.edit(**kwargs)
        except TypeError:
            await message.edit(content=content)

    async def send_notification(self, message: str) -> Dict[str, Any]:
        channel_id = str(self._config.config.get("notification_channel_id", "")).strip()
        if not channel_id:
            raise ValueError("notification_channel_id is required")
        if self._status != "running" or not self._client:
            raise RuntimeError("Discord connector is not running")

        try:
            channel_id_int = int(channel_id)
        except ValueError as exc:
            raise ValueError("notification_channel_id must be a numeric Discord channel ID") from exc

        channel = self._client.get_channel(channel_id_int)
        if channel is None and hasattr(self._client, "fetch_channel"):
            channel = await self._client.fetch_channel(channel_id_int)
        if channel is None or not hasattr(channel, "send"):
            raise RuntimeError(f"Discord channel not found: {channel_id}")

        sent = await self._send_text(channel, message)
        return {
            "channel_id": channel_id,
            "message_id": str(getattr(sent, "id", "") or ""),
        }

    async def start(self) -> None:
        if self._bot_task and not self._bot_task.done():
            await self.stop()

        bot_token = str(self._config.config.get("bot_token", "")).strip()
        if not bot_token:
            self._status = "error"
            self._status_message = "Bot Token is not configured"
            self._record_error("Bot Token is required")
            raise ValueError("Bot Token is required")

        try:
            import discord
        except ImportError:
            self._status = "error"
            self._status_message = "discord.py is not installed. Run: pip install discord.py"
            self._record_error("discord.py is not installed")
            raise ImportError("discord.py is not installed")

        intents = discord.Intents.default()
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = bool(self._config.config.get("request_message_content_intent", False))

        self._client = discord.Client(intents=intents)
        self._ready_event = asyncio.Event()

        @self._client.event
        async def on_ready():
            self._status = "running"
            self._start_time = time.time()
            self._status_message = f"Logged in as {self._client.user} (ID: {self._client.user.id})"
            self._clear_error()
            self._record_event("info", f"Discord bot ready: {self._client.user}")
            if self._ready_event:
                self._ready_event.set()
            logger.info("[Discord] Bot ready: %s", self._client.user)

        @self._client.event
        async def on_disconnect():
            self._status = "error"
            self._status_message = "Disconnected; Discord client will attempt to reconnect."
            self._record_error("Discord disconnected; reconnecting")
            logger.warning("[Discord] Disconnected, auto-reconnecting...")

        @self._client.event
        async def on_resumed():
            self._status = "running"
            self._start_time = time.time()
            self._status_message = "Discord session resumed"
            self._clear_error()
            self._record_event("info", "Discord session resumed")
            logger.info("[Discord] Session resumed")

        @self._client.event
        async def on_error(event: str, *args, **kwargs):
            logger.error("[Discord] Error in %s: args=%s kwargs=%s", event, args, kwargs)

        @self._client.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)

        self._status = "stopped"
        self._status_message = "Connecting to Discord..."
        self._bot_task = asyncio.create_task(self._client.start(bot_token))

        def _on_done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            with suppress(asyncio.CancelledError):
                exc = task.exception()
                if exc:
                    msg = self._discord_exception_message(exc)
                    self._status = "error"
                    self._status_message = msg
                    self._record_error(msg)

        self._bot_task.add_done_callback(_on_done)
        ready_task = asyncio.create_task(self._ready_event.wait())
        try:
            done, pending = await asyncio.wait(
                {ready_task, self._bot_task},
                timeout=self._STARTUP_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                if task is ready_task:
                    task.cancel()
            if self._bot_task in done:
                await self._bot_task
            if ready_task not in done:
                msg = f"Discord bot did not become ready within {self._STARTUP_TIMEOUT}s"
                await self.stop()
                self._status = "error"
                self._status_message = msg
                self._record_error(msg)
                raise TimeoutError(msg)
        except Exception as exc:
            msg = self._discord_exception_message(exc)
            self._status = "error"
            self._status_message = msg
            self._record_error(msg)
            raise
        finally:
            if not ready_task.done():
                ready_task.cancel()

    async def stop(self) -> None:
        task = self._bot_task
        self._bot_task = None
        if task and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._status = "stopped"
        self._status_message = ""
        self._start_time = 0
        self._record_event("info", "Discord bot stopped")
        logger.info("[Discord] Bot stopped")

    async def _handle_message(self, message: Any) -> None:
        import discord

        if message.author == self._client.user:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        mentioned = self._client.user in message.mentions

        if not is_dm and not mentioned:
            return

        content = message.content or ""
        if mentioned and not is_dm:
            for mention_text in (f"<@{self._client.user.id}>", f"<@!{self._client.user.id}>"):
                content = content.replace(mention_text, "")
            content = content.strip()

        if not content:
            await self._send_text(message.channel, "Hello! Send a message to start a conversation.")
            return

        user_id = str(message.author.id)
        channel_id = str(message.channel.id) if not is_dm else "dm"

        display_name = getattr(message.author, "display_name", "")
        author_name = getattr(message.author, "name", "") or display_name
        avatar = getattr(message.author, "display_avatar", None)
        avatar_url = str(avatar.url) if avatar else ""
        timestamp = (
            message.created_at.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if getattr(message, "created_at", None)
            else ""
        )

        reference = getattr(message, "reference", None)
        reply_to = str(getattr(reference, "message_id", "") or "") if reference else ""
        thread_obj = None
        try:
            if isinstance(message.channel, discord.Thread):
                thread_obj = message.channel
        except Exception:
            thread_obj = None
        thread_id = str(getattr(thread_obj, "id", "")) if thread_obj else ""
        if not thread_id and reply_to:
            thread_id = reply_to

        raw_meta: Dict[str, Any] = {}
        if not is_dm:
            guild_name = message.guild.name if message.guild else "unknown"
            guild_id = str(message.guild.id) if message.guild else ""
            channel_name = getattr(message.channel, "name", str(message.channel.id))
            raw_meta["server"] = f"{guild_name} ({guild_id})"
            raw_meta["channel_name"] = f"#{channel_name}"
        if timestamp:
            raw_meta["sent_at"] = timestamp
        if avatar_url:
            raw_meta["avatar"] = avatar_url
        raw_meta["author_handle"] = f"@{author_name}"
        raw_meta["system_note"] = (
            "Reply directly to the sender in Discord. Do not inspect, start, stop, or "
            "configure connectors unless the sender explicitly asks. Keep replies concise."
        )
        attachments = getattr(message, "attachments", []) or []
        att_urls = [a.url for a in attachments if hasattr(a, "url")]
        if att_urls:
            raw_meta["attachments"] = ", ".join(att_urls[:3])

        from app.gateway import MessageEnvelope, dispatch
        from app.gateway.translators.discord import DiscordTranslator

        envelope = MessageEnvelope(
            platform="discord",
            channel_id=channel_id,
            user_id=user_id,
            text=content,
            thread_id=thread_id,
            reply_to=reply_to or None,
            sender_name=display_name or author_name,
            is_dm=is_dm,
            raw_meta=raw_meta,
        )
        translator = DiscordTranslator(
            channel=message.channel,
            reply_to=message if reply_to else None,
            tool_visibility=self.tool_visibility,
        )
        self._record_event(
            "info", "Discord message received",
            channel_id=channel_id, dm=is_dm, thread=bool(thread_id),
        )

        try:
            session_id = await dispatch(
                self, envelope, translator, timeout_s=self._AGENT_RUN_TIMEOUT,
            )
            self._clear_error()
            self._record_event("info", "Discord Agent reply sent", session_id=session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[Discord] dispatch failed: %s", exc)
            self._record_error(f"Discord dispatch failed: {exc}")
