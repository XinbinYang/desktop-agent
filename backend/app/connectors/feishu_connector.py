import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

from app.connectors.base import ConnectorConfig, PlatformConnector
from app.config import load_config

logger = logging.getLogger(__name__)

# Cache for user real names: {open_id: (name, cached_timestamp)}
_USER_NAME_CACHE: Dict[str, tuple] = {}
_USER_NAME_CACHE_TTL = 300  # 5 minutes


class FeishuConnector(PlatformConnector):
    name = "feishu"
    display_name = "飞书"
    description = "通过飞书 Bot 远程与 Agent 对话，支持单聊和群聊 @提及触发。"

    _AGENT_RUN_TIMEOUT = 300  # seconds

    def __init__(self, config: Optional[ConnectorConfig] = None):
        super().__init__(config)
        self._status = "stopped"
        self._status_message = ""
        self._ws_client = None
        self._api_client = None
        self._task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._ws_thread_exited = False

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
                "app_id": {
                    "type": "string",
                    "label": "App ID",
                    "description": "飞书开放平台应用的 App ID",
                },
                "app_secret": {
                    "type": "string",
                    "label": "App Secret",
                    "description": "飞书开放平台应用的 App Secret",
                    "sensitive": True,
                },
                "verification_token": {
                    "type": "string",
                    "label": "Verification Token",
                    "description": "飞书事件订阅的 Verification Token（可选，WebSocket 模式可留空）",
                    "sensitive": True,
                },
            },
            "required": ["app_id", "app_secret"],
        }

    async def health_check(self) -> Dict[str, Any]:
        if not self._api_client:
            return {"healthy": False, "latency_ms": None, "details": "API 客户端未初始化"}
        try:
            start = time.time()
            resp = self._api_client.auth.v3.tenant_access_token.internal.create()
            elapsed = (time.time() - start) * 1000
            healthy = resp.success()
            return {
                "healthy": healthy,
                "latency_ms": round(elapsed, 1),
                "details": "" if healthy else f"code={resp.code} msg={resp.msg}",
            }
        except Exception as e:
            return {"healthy": False, "latency_ms": None, "details": str(e)}

    async def start(self) -> None:
        app_id = self._config.config.get("app_id", "").strip()
        app_secret = self._config.config.get("app_secret", "").strip()

        if not app_id or not app_secret:
            self._status = "error"
            self._status_message = "App ID 和 App Secret 未配置"
            raise ValueError("App ID and App Secret are required")

        try:
            import lark_oapi
            from lark_oapi.ws import Client as WsClient
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError:
            self._status = "error"
            self._status_message = "lark-oapi 未安装，请运行: pip install lark-oapi"
            raise ImportError("lark-oapi is not installed")

        handler_builder = (
            EventDispatcherHandlerBuilder(
                encrypt_key="",
                verification_token=self._config.config.get("verification_token", ""),
            )
            .register_p2_im_message_receive_v1(self._on_message_receive)
        )
        event_handler = handler_builder.build()

        self._api_client = lark_oapi.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .build()

        self._ws_client = WsClient(
            app_id=app_id,
            app_secret=app_secret,
            event_handler=event_handler,
            log_level=lark_oapi.LogLevel.WARN,
        )

        self._ws_thread_exited = False
        self._status = "running"
        self._start_time = time.time()
        self._status_message = "飞书 Bot 已连接"

        self._task = asyncio.create_task(
            asyncio.to_thread(self._ws_client.start)
        )

        # Watchdog: monitor WS thread health
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        logger.info("[Feishu] Bot started, App ID: %s", app_id)

    async def stop(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        self._ws_client = None
        self._api_client = None
        self._status = "stopped"
        self._status_message = ""
        self._start_time = 0
        logger.info("[Feishu] Bot stopped")

    async def _watchdog_loop(self) -> None:
        """Monitor WebSocket thread health. Auto-restart if died and enabled."""
        try:
            while True:
                await asyncio.sleep(30)
                if self._task is None or self._task.done():
                    if self._config.enabled and self._status != "error":
                        exc = self._task.exception() if self._task else None
                        logger.warning("[Feishu] WS thread died, attempting restart. Exception: %s", exc)
                        try:
                            await self.start()
                            return
                        except Exception as e:
                            self._status = "error"
                            self._status_message = f"自动重启失败: {e}"
                            logger.error("[Feishu] Auto-restart failed: %s", e)
                    break
        except asyncio.CancelledError:
            pass

    def _on_message_receive(self, event: Any) -> None:
        try:
            asyncio.create_task(self._handle_feishu_message(event))
        except Exception as e:
            logger.error("[Feishu] Failed to schedule message handler: %s", e)

    def _lookup_user_name(self, open_id: str) -> str:
        """Look up a user's real name by open_id, with caching."""
        now = time.time()
        cached = _USER_NAME_CACHE.get(open_id)
        if cached:
            name, ts = cached
            if now - ts < _USER_NAME_CACHE_TTL:
                return name

        if not self._api_client:
            return open_id

        try:
            from lark_oapi.api.contact.v3 import GetUserRequest
            req = GetUserRequest.builder() \
                .user_id(open_id) \
                .user_id_type("open_id") \
                .build()
            resp = self._api_client.contact.v3.user.get(req)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name or open_id
                _USER_NAME_CACHE[open_id] = (name, now)
                return name
        except Exception as e:
            logger.debug("[Feishu] User lookup failed for %s: %s", open_id, e)

        return open_id

    async def _handle_feishu_message(self, event: Any) -> None:
        event_data = event.event if hasattr(event, "event") else getattr(event, "event", None)
        if not event_data:
            return

        message = event_data.message if hasattr(event_data, "message") else None
        if not message:
            return

        chat_type = getattr(message, "chat_type", "unknown")
        chat_id = getattr(message, "chat_id", "")
        message_id = getattr(message, "message_id", "")
        msg_type = getattr(message, "message_type", "text")

        if chat_type not in ("p2p", "group"):
            return

        # Sender info
        sender = getattr(event_data, "sender", None)
        sender_id = ""
        if sender:
            sid_dict = getattr(sender, "sender_id", {})
            if isinstance(sid_dict, dict):
                sender_id = sid_dict.get("open_id", "") or sid_dict.get("user_id", "")

        if not sender_id:
            return

        # Lookup real name via Feishu Contact API (with cache)
        sender_name = self._lookup_user_name(sender_id)

        # Extract text content
        content_json = getattr(message, "content", "{}")
        try:
            content_obj = json.loads(content_json) if isinstance(content_json, str) else content_json
            text = content_obj.get("text", "")
        except (json.JSONDecodeError, TypeError):
            text = ""

        if not text:
            return

        # Group chat @mention check
        if chat_type == "group":
            mentions = getattr(message, "mentions", []) or []
            bot_mentioned = any(
                getattr(m, "name", "") == self._config.config.get("bot_name", "")
                for m in mentions
            )
            if not bot_mentioned and "@" not in text:
                return

        session_id = self.get_session_id(sender_id, chat_id)

        # Cancel previous run for same session
        self.cancel_session_run(session_id)

        # Build rich context
        chat_name = getattr(event_data, "chat_name", "") or chat_id
        ctx_lines = ["[飞书消息]"]
        ctx_lines.append(f"发送者: {sender_name} (Open ID: {sender_id})")
        ctx_lines.append(f"聊天类型: {chat_type}")
        ctx_lines.append(f"聊天名称: {chat_name}")
        ctx_lines.append(f"消息类型: {msg_type}")
        context_prefix = "\n".join(ctx_lines) + "\n\n"

        from app.agent import get_or_create_session

        default_model = load_config().settings.default_model
        session = get_or_create_session(session_id, default_model, role_id="desktop-agent")

        reply_msg_id = self._send_text_message(chat_id, message_id, "⏳ 思考中...")

        start_time = time.time()
        full_content = ""
        last_edit_time = 0
        EDIT_INTERVAL = 2.0

        async def _do_run():
            nonlocal full_content, last_edit_time
            try:
                async for ev in session.run(context_prefix + text, None):
                    if ev["type"] == "content":
                        full_content += ev["data"].get("text", "")
                        if reply_msg_id and (time.time() - last_edit_time) > EDIT_INTERVAL:
                            self._edit_text_message(reply_msg_id, full_content[:3000])
                            last_edit_time = time.time()
            except Exception as e:
                logger.warning("[Feishu] Agent run error: %s", e)
                full_content = f"[ERROR] 处理消息时出错: {e}"

        task = asyncio.create_task(_do_run())
        self._running_tasks[session_id] = task

        try:
            await asyncio.wait_for(task, timeout=self._AGENT_RUN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("[Feishu] Agent run timed out after %ss", self._AGENT_RUN_TIMEOUT)
            full_content = f"[TIMEOUT] Agent 处理超时（{self._AGENT_RUN_TIMEOUT}s）"
            task.cancel()
        except asyncio.CancelledError:
            pass

        self._running_tasks.pop(session_id, None)

        elapsed = time.time() - start_time

        if not full_content:
            full_content = "Agent 已完成，但未生成回复内容。"
        footer = f"\n\n---\n⏱️ 耗时 {elapsed:.1f}s"
        final = full_content + footer

        if reply_msg_id:
            self._edit_text_message(reply_msg_id, final[:3000])
        else:
            self._send_text_message(chat_id, message_id, final[:3000])

    def _send_text_message(self, chat_id: str, root_id: str, text: str) -> str:
        if not self._api_client:
            return ""
        try:
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("text") \
                .content(json.dumps({"text": text})) \
                .build()

            req = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            resp = self._api_client.im.v1.message.create(req)
            if resp.success():
                return resp.data.message_id or ""
            else:
                logger.warning("[Feishu] Send message failed: code=%s msg=%s", resp.code, resp.msg)
                return ""
        except Exception as e:
            logger.warning("[Feishu] Send message error: %s", e)
            return ""

    def _edit_text_message(self, message_id: str, text: str) -> bool:
        if not self._api_client or not message_id:
            return False
        try:
            from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody

            body = UpdateMessageRequestBody.builder() \
                .msg_type("text") \
                .content(json.dumps({"text": text})) \
                .build()

            req = UpdateMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(body) \
                .build()

            resp = self._api_client.im.v1.message.update(req)
            if not resp.success():
                logger.debug("[Feishu] Update message failed: code=%s msg=%s", resp.code, resp.msg)
                return False
            return True
        except Exception as e:
            logger.debug("[Feishu] Update message error: %s", e)
            return False
