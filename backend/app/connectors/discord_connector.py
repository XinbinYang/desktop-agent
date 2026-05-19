import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.connectors.base import ConnectorConfig, PlatformConnector, target_agent_config_schema

logger = logging.getLogger(__name__)


class DiscordConnector(PlatformConnector):
    name = "discord"
    display_name = "Discord"
    description = "通过 Discord Bot 远程与 Agent 对话，支持 DM 和 @提及触发。"

    def __init__(self, config: Optional[ConnectorConfig] = None):
        super().__init__(config)
        self._status = "stopped"
        self._status_message = ""
        self._client = None
        self._bot_task: Optional[asyncio.Task] = None

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
                    "description": "Discord 开发者门户中创建的 Bot Token",
                    "sensitive": True,
                },
                "target_agent": target_agent_config_schema(),
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
        details = self._status_message
        if self._client and hasattr(self._client, "is_ready"):
            healthy = healthy and self._client.is_ready()
        return {"healthy": healthy, "latency_ms": latency, "details": details}

    async def start(self) -> None:
        bot_token = self._config.config.get("bot_token", "").strip()
        if not bot_token:
            self._status = "error"
            self._status_message = "Bot Token 未配置"
            raise ValueError("Bot Token is required")

        try:
            import discord
        except ImportError:
            self._status = "error"
            self._status_message = "discord.py 未安装，请运行: pip install discord.py"
            raise ImportError("discord.py is not installed")

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            self._status = "running"
            self._start_time = time.time()
            self._status_message = f"已登录: {self._client.user} (ID: {self._client.user.id})"
            logger.info("[Discord] Bot ready: %s", self._client.user)

        @self._client.event
        async def on_disconnect():
            self._status = "error"
            self._status_message = "连接断开，自动重连中..."
            logger.warning("[Discord] Disconnected, auto-reconnecting...")

        @self._client.event
        async def on_resumed():
            self._status = "running"
            self._start_time = time.time()
            self._status_message = "已重新连接"
            logger.info("[Discord] Session resumed")

        @self._client.event
        async def on_error(event: str, *args, **kwargs):
            logger.error("[Discord] Error in %s: args=%s kwargs=%s", event, args, kwargs)

        @self._client.event
        async def on_message(message: discord.Message):
            await self._handle_message(message)

        try:
            self._status = "running"
            self._start_time = time.time()
            self._bot_task = asyncio.create_task(self._client.start(bot_token))
        except discord.LoginFailure as e:
            self._status = "error"
            self._status_message = f"Token 无效: {e}"
            raise
        except Exception as e:
            self._status = "error"
            self._status_message = f"启动失败: {e}"
            raise

    async def stop(self) -> None:
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            self._bot_task = None
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        self._status = "stopped"
        self._status_message = ""
        self._start_time = 0
        logger.info("[Discord] Bot stopped")

    async def _handle_message(self, message: Any) -> None:
        import discord

        if message.author == self._client.user:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        mentioned = self._client.user in message.mentions

        if not is_dm and not mentioned:
            return

        content = message.content
        if mentioned and not is_dm:
            content = message.content.replace(f"<@{self._client.user.id}>", "").strip()
            content = message.content.replace(f"<@!{self._client.user.id}>", "").strip()

        if not content:
            await message.channel.send("你好！有什么可以帮你的吗？请发送一条消息来开始对话。")
            return

        user_id = str(message.author.id)
        channel_id = str(message.channel.id) if not is_dm else "dm"
        session_id = self.get_session_id(user_id, channel_id)

        # Cancel any previous run for the same session
        self.cancel_session_run(session_id)

        # Build rich context
        display_name = message.author.display_name
        author_name = message.author.name
        avatar_url = str(message.author.display_avatar.url) if message.author.display_avatar else ""
        timestamp = message.created_at.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if message.created_at else ""

        ctx_lines = ["[Discord 消息]"]
        ctx_lines.append(f"发送者: {display_name} (@{author_name}, ID: {user_id})")
        if avatar_url:
            ctx_lines.append(f"头像: {avatar_url}")

        if not is_dm:
            guild_name = message.guild.name if message.guild else "unknown"
            guild_id = str(message.guild.id) if message.guild else ""
            channel_name = getattr(message.channel, "name", str(message.channel.id))
            ctx_lines.append(f"服务器: {guild_name} (ID: {guild_id})")
            ctx_lines.append(f"频道: #{channel_name} (ID: {channel_id})")
        else:
            ctx_lines.append("频道: 私信 (DM)")

        if timestamp:
            ctx_lines.append(f"发送时间: {timestamp}")

        attachments = getattr(message, "attachments", []) or []
        if attachments:
            att_urls = [a.url for a in attachments if hasattr(a, "url")]
            if att_urls:
                ctx_lines.append(f"附件: {', '.join(att_urls[:3])}")

        context_prefix = "\n".join(ctx_lines) + "\n\n"

        from app.agent import get_or_create_session

        agent_type, role_id, model_id = self.resolve_agent_target()
        session = get_or_create_session(session_id, model_id, role_id=role_id, agent_type=agent_type)

        placeholder = None
        try:
            placeholder = await message.channel.send("⏳ 思考中...")
        except discord.HTTPException:
            pass

        start_time = time.time()
        full_content = ""
        last_edit_time = 0
        EDIT_INTERVAL = 0.5

        async def _do_run():
            nonlocal full_content, last_edit_time

            try:
                async for event in session.run(context_prefix + content, None):
                    if event["type"] == "content":
                        full_content += event["data"].get("text", "")

                        if placeholder and (time.time() - last_edit_time) > EDIT_INTERVAL:
                            display = full_content
                            if len(display) > 1900:
                                display = display[:1900] + "\n\n..."
                            try:
                                await placeholder.edit(content=display)
                            except discord.HTTPException:
                                pass
                            last_edit_time = time.time()

                    elif event["type"] == "tool_call":
                        tool_data = event["data"]
                        tool_name = tool_data.get("name", "")
                        duration = tool_data.get("duration_ms", 0)
                        duration_str = f"{duration / 1000:.1f}s" if duration else ""

                        embed = discord.Embed(
                            title=f"\U0001f527 {tool_name}",
                            color=0x5865F2,
                        )
                        args = tool_data.get("args", {})
                        if args:
                            args_str = ", ".join(
                                f"{k}={str(v)[:100]}" for k, v in args.items()
                            )
                            if len(args_str) > 800:
                                args_str = args_str[:800] + "..."
                            embed.add_field(name="参数", value=args_str, inline=False)

                        result = tool_data.get("result", "")
                        if result:
                            result_display = result[:800] + ("..." if len(result) > 800 else "")
                            embed.add_field(name="结果", value=result_display, inline=False)

                        if duration_str:
                            embed.set_footer(text=f"耗时: {duration_str}")

                        try:
                            await message.channel.send(embed=embed)
                        except discord.HTTPException:
                            pass

            except Exception as e:
                logger.warning("[Discord] Agent run error: %s", e)
                error_msg = f"处理消息时出错: {e}"
                full_content = f"[ERROR] {error_msg}"

        task = asyncio.create_task(_do_run())
        self._running_tasks[session_id] = task

        try:
            await task
        except asyncio.CancelledError:
            pass

        self._running_tasks.pop(session_id, None)

        elapsed = time.time() - start_time

        if not full_content:
            full_content = "Agent 已完成，但未生成回复内容。"
        footer = f"\n\n---\n⏱️ 耗时 {elapsed:.1f}s"
        final = full_content + footer

        if placeholder:
            if len(final) <= 2000:
                try:
                    await placeholder.edit(content=final)
                except discord.HTTPException:
                    pass
            else:
                try:
                    await placeholder.edit(content=final[:1900] + "\n\n...(续)")
                except discord.HTTPException:
                    pass
                remaining = final[1900:]
                for i in range(0, len(remaining), 1900):
                    chunk = remaining[i:i + 1900]
                    try:
                        await message.channel.send(chunk)
                    except discord.HTTPException:
                        break
        else:
            for i in range(0, len(final), 1900):
                chunk = final[i:i + 1900]
                try:
                    await message.channel.send(chunk)
                except discord.HTTPException:
                    break
