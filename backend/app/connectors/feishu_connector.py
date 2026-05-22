import asyncio
import json
import logging
import time
from collections import deque
from contextlib import suppress
from typing import Any, Dict, Optional

from app.connectors.base import (
    ConnectorConfig,
    PlatformConnector,
    target_agent_config_schema,
    tool_visibility_config_schema,
)

logger = logging.getLogger(__name__)

_USER_NAME_CACHE: Dict[str, tuple] = {}
_USER_NAME_CACHE_TTL = 300

_DOMAIN_URLS = {
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
}


class FeishuConnector(PlatformConnector):
    name = "feishu"
    display_name = "飞书"
    description = "通过飞书 Bot 远程与 Agent 对话，支持单聊和群聊 @提及触发。"

    _AGENT_RUN_TIMEOUT = 300

    def __init__(self, config: Optional[ConnectorConfig] = None):
        super().__init__(config)
        self._status = "stopped"
        self._status_message = ""
        self._ws_client = None
        self._api_client = None
        self._task: Optional[asyncio.Task] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._event_ids: deque[str] = deque(maxlen=1000)
        self._event_id_set: set[str] = set()
        self._last_send_error = ""

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
                "domain": {
                    "type": "string",
                    "label": "Domain",
                    "description": "Feishu China or Lark international Open Platform domain",
                    "enum": ["feishu", "lark"],
                    "enumLabels": {"feishu": "Feishu (China)", "lark": "Lark (International)"},
                    "default": "feishu",
                },
                "app_id": {
                    "type": "string",
                    "label": "App ID",
                    "description": "Feishu/Lark Open Platform App ID",
                },
                "app_secret": {
                    "type": "string",
                    "label": "App Secret",
                    "description": "Feishu/Lark Open Platform App Secret",
                    "sensitive": True,
                },
                "verification_token": {
                    "type": "string",
                    "label": "Verification Token",
                    "description": "Optional in WebSocket long-connection mode",
                    "sensitive": True,
                },
                "bot_open_id": {
                    "type": "string",
                    "label": "Bot Open ID",
                    "description": "Optional; improves group @mention matching when known",
                },
                "target_agent": target_agent_config_schema(),
                "tool_visibility": tool_visibility_config_schema(),
                "notifications_enabled": {
                    "type": "boolean",
                    "label": "Enable Notifications",
                    "description": "Allow Desktop Agent to send proactive Feishu notifications",
                    "default": False,
                },
                "notification_chat_id": {
                    "type": "string",
                    "label": "Notification Chat ID",
                    "description": "Feishu/Lark chat_id used by the test-message endpoint",
                },
            },
            "required": ["app_id", "app_secret"],
        }

    def _domain_url(self) -> str:
        raw = str(self._config.config.get("domain") or "feishu").strip().lower()
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw.rstrip("/")
        return _DOMAIN_URLS.get(raw, _DOMAIN_URLS["feishu"])

    async def health_check(self) -> Dict[str, Any]:
        if not self._api_client:
            return {"healthy": False, "latency_ms": None, "details": "API client is not initialized"}
        try:
            start = time.time()
            resp = await asyncio.to_thread(self._tenant_token_response)
            elapsed = (time.time() - start) * 1000
            healthy = resp.success()
            return {
                "healthy": healthy and self._status == "running",
                "latency_ms": round(elapsed, 1),
                "details": "" if healthy else self._response_detail(resp),
            }
        except Exception as exc:
            return {"healthy": False, "latency_ms": None, "details": str(exc)}

    async def doctor(self) -> Dict[str, Any]:
        data = await super().doctor()
        data["domain_url"] = self._domain_url()
        data["dependencies"] = {"lark-oapi": self._dependency_available("lark_oapi")}
        if not data["dependencies"]["lark-oapi"]:
            data["recommendations"].append(
                r"Install Feishu/Lark support: backend\\venv\\Scripts\\python.exe -m pip install lark-oapi"
            )
        data["recommendations"].extend([
            "Use WebSocket long-connection mode and subscribe to im.message.receive_v1.",
            "Publish or approve the app before expecting message events.",
            "Add the bot to the target group; group chats require @mention by default.",
            "Grant im:message and im:message:send_as_bot permissions.",
        ])
        if self._last_send_error:
            data["last_send_error"] = self._last_send_error
        return data

    def _dependency_available(self, module_name: str) -> bool:
        try:
            import importlib.util
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    async def send_notification(self, message: str) -> Dict[str, Any]:
        chat_id = str(self._config.config.get("notification_chat_id", "")).strip()
        if not chat_id:
            raise ValueError("notification_chat_id is required")
        if self._status != "running" or not self._api_client:
            raise RuntimeError("Feishu connector is not running")

        message_id = self._send_text_message(chat_id, "", message)
        if not message_id:
            raise RuntimeError(self._last_send_error or "Feishu message send failed")
        return {"chat_id": chat_id, "message_id": message_id}

    async def start(self) -> None:
        app_id = str(self._config.config.get("app_id", "")).strip()
        app_secret = str(self._config.config.get("app_secret", "")).strip()
        if not app_id or not app_secret:
            self._status = "error"
            self._status_message = "App ID and App Secret are required"
            self._record_error(self._status_message)
            raise ValueError(self._status_message)

        try:
            import lark_oapi
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandlerBuilder
            from lark_oapi.ws import Client as WsClient
        except ImportError:
            self._status = "error"
            self._status_message = "lark-oapi is not installed. Run: pip install lark-oapi"
            self._record_error("lark-oapi is not installed")
            raise ImportError("lark-oapi is not installed")

        await self.stop()
        self._loop = asyncio.get_running_loop()

        domain_url = self._domain_url()
        handler_builder = (
            EventDispatcherHandlerBuilder(
                encrypt_key="",
                verification_token=str(self._config.config.get("verification_token") or ""),
            )
            .register_p2_im_message_receive_v1(self._on_message_receive)
        )

        self._api_client = (
            lark_oapi.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(domain_url)
            .build()
        )

        resp = await asyncio.to_thread(self._tenant_token_response)
        if not resp.success():
            detail = self._response_detail(resp)
            self._status = "error"
            self._status_message = f"Feishu token validation failed: {detail}"
            self._record_error(self._status_message)
            raise RuntimeError(self._status_message)

        self._ws_client = WsClient(
            app_id=app_id,
            app_secret=app_secret,
            event_handler=handler_builder.build(),
            log_level=lark_oapi.LogLevel.WARN,
            domain=domain_url,
            auto_reconnect=True,
        )

        self._status = "running"
        self._start_time = time.time()
        self._status_message = f"Feishu/Lark Bot connected via {domain_url}"
        self._clear_error()
        self._record_event("info", self._status_message)

        self._task = asyncio.create_task(asyncio.to_thread(self._ws_client.start))
        self._task.add_done_callback(self._on_ws_done)
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("[Feishu] Bot started, App ID: %s, domain=%s", app_id, domain_url)

    async def stop(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watchdog_task
        self._watchdog_task = None

        if self._ws_client:
            stop_fn = getattr(self._ws_client, "stop", None) or getattr(self._ws_client, "close", None)
            if callable(stop_fn):
                with suppress(Exception):
                    await asyncio.to_thread(stop_fn)

        if self._task and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._ws_client = None
        self._api_client = None
        self._loop = None
        self._status = "stopped"
        self._status_message = ""
        self._start_time = 0
        self._record_event("info", "Feishu/Lark bot stopped")
        logger.info("[Feishu] Bot stopped")

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                if self._task is None or self._task.done():
                    if self._config.enabled and self._status != "error":
                        exc = self._task.exception() if self._task and not self._task.cancelled() else None
                        logger.warning("[Feishu] WS thread died, attempting restart. Exception: %s", exc)
                        try:
                            await self.start()
                            return
                        except Exception as restart_exc:
                            self._status = "error"
                            self._status_message = f"Auto-restart failed: {restart_exc}"
                            self._record_error(self._status_message)
                    break
        except asyncio.CancelledError:
            pass

    def _on_ws_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        with suppress(asyncio.CancelledError):
            exc = task.exception()
            if exc:
                self._status = "error"
                self._status_message = f"Feishu WebSocket stopped: {exc}"
                self._record_error(self._status_message)

    def _on_message_receive(self, event: Any) -> None:
        if not self._loop or not self._loop.is_running():
            self._record_error("Feishu event received without an active asyncio loop")
            return
        future = asyncio.run_coroutine_threadsafe(self._handle_feishu_message(event), self._loop)

        def _done(fut) -> None:
            exc = fut.exception()
            if exc:
                self._record_error(f"Feishu message handler failed: {exc}")
                logger.error("[Feishu] Message handler failed: %s", exc)

        future.add_done_callback(_done)

    def _tenant_token_response(self) -> Any:
        return self._api_client.auth.v3.tenant_access_token.internal.create()

    def _response_detail(self, resp: Any) -> str:
        code = getattr(resp, "code", "")
        msg = getattr(resp, "msg", "")
        log_id = ""
        get_log_id = getattr(resp, "get_log_id", None)
        if callable(get_log_id):
            with suppress(Exception):
                log_id = get_log_id()
        detail = f"code={code} msg={msg}".strip()
        if log_id:
            detail += f" log_id={log_id}"
        return detail or str(resp)

    def _event_id(self, event: Any) -> str:
        header = getattr(event, "header", None)
        for source in (header, event):
            if not source:
                continue
            event_id = getattr(source, "event_id", "") or getattr(source, "uuid", "")
            if event_id:
                return str(event_id)
        return ""

    def _dedupe_event(self, event_id: str) -> bool:
        if not event_id:
            return False
        if event_id in self._event_id_set:
            return True
        if len(self._event_ids) == self._event_ids.maxlen:
            old = self._event_ids.popleft()
            self._event_id_set.discard(old)
        self._event_ids.append(event_id)
        self._event_id_set.add(event_id)
        return False

    def _lookup_user_name(self, open_id: str) -> str:
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
            req = GetUserRequest.builder().user_id(open_id).user_id_type("open_id").build()
            resp = self._api_client.contact.v3.user.get(req)
            if resp.success() and resp.data and resp.data.user:
                name = resp.data.user.name or open_id
                _USER_NAME_CACHE[open_id] = (name, now)
                return name
        except Exception as exc:
            logger.debug("[Feishu] User lookup failed for %s: %s", open_id, exc)
        return open_id

    async def _handle_feishu_message(self, event: Any) -> None:
        event_id = self._event_id(event)
        if self._dedupe_event(event_id):
            self._record_event("info", "Duplicate Feishu event ignored", event_id=event_id)
            return

        event_data = getattr(event, "event", None)
        if not event_data:
            return
        message = getattr(event_data, "message", None)
        if not message:
            return

        chat_type = getattr(message, "chat_type", "unknown")
        chat_id = getattr(message, "chat_id", "")
        message_id = getattr(message, "message_id", "")
        msg_type = getattr(message, "message_type", "text")
        if chat_type not in ("p2p", "group"):
            return

        sender_id = self._sender_open_id(event_data)
        if not sender_id:
            return

        text = self._message_text(message)
        if not text:
            return

        if chat_type == "group" and not self._group_message_mentions_bot(message, text):
            return
        text = self._strip_mentions(message, text).strip()
        if not text:
            return

        sender_name = self._lookup_user_name(sender_id)
        chat_name = getattr(event_data, "chat_name", "") or chat_id

        parent_id = str(getattr(message, "parent_id", "") or "")
        root_id = str(getattr(message, "root_id", "") or "")
        thread_key = root_id or parent_id

        raw_meta: Dict[str, Any] = {
            "chat_type": chat_type,
            "chat_name": chat_name,
            "msg_type": msg_type,
        }
        if event_id:
            raw_meta["event_id"] = event_id
        if message_id:
            raw_meta["root_message_id"] = message_id

        from app.gateway import MessageEnvelope, dispatch
        from app.gateway.translators.feishu import FeishuCardTranslator

        envelope = MessageEnvelope(
            platform="feishu",
            channel_id=chat_id,
            user_id=sender_id,
            text=text,
            thread_id=thread_key,
            reply_to=parent_id or None,
            sender_name=sender_name,
            is_dm=(chat_type == "p2p"),
            raw_meta=raw_meta,
        )
        translator = FeishuCardTranslator(
            self._api_client,
            chat_id=chat_id,
            root_id=message_id,
            tool_visibility=self.tool_visibility,
        )

        try:
            session_id = await dispatch(
                self, envelope, translator, timeout_s=self._AGENT_RUN_TIMEOUT,
            )
            self._clear_error()
            self._record_event("info", "Feishu Agent reply sent", session_id=session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[Feishu] dispatch failed: %s", exc)
            self._record_error(f"Feishu dispatch failed: {exc}")

    def _sender_open_id(self, event_data: Any) -> str:
        sender = getattr(event_data, "sender", None)
        if not sender:
            return ""
        sid_dict = getattr(sender, "sender_id", {})
        if isinstance(sid_dict, dict):
            return sid_dict.get("open_id", "") or sid_dict.get("user_id", "")
        open_id = getattr(sid_dict, "open_id", "") or getattr(sid_dict, "user_id", "")
        return str(open_id or "")

    def _message_text(self, message: Any) -> str:
        content_json = getattr(message, "content", "{}")
        try:
            content_obj = json.loads(content_json) if isinstance(content_json, str) else content_json
            return str(content_obj.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            return ""

    def _mention_open_id(self, mention: Any) -> str:
        mention_id = getattr(mention, "id", {}) or getattr(mention, "mention_id", {})
        if isinstance(mention_id, dict):
            return str(mention_id.get("open_id", "") or mention_id.get("user_id", ""))
        return str(getattr(mention_id, "open_id", "") or getattr(mention_id, "user_id", ""))

    def _group_message_mentions_bot(self, message: Any, text: str) -> bool:
        mentions = getattr(message, "mentions", []) or []
        if not mentions:
            return "@" in text
        bot_open_id = str(self._config.config.get("bot_open_id", "")).strip()
        if not bot_open_id:
            return True
        return any(self._mention_open_id(m) == bot_open_id for m in mentions)

    def _strip_mentions(self, message: Any, text: str) -> str:
        for mention in getattr(message, "mentions", []) or []:
            for attr in ("key", "name"):
                value = str(getattr(mention, attr, "") or "")
                if value:
                    text = text.replace(value, "")
        return text

    def _send_text_message(self, chat_id: str, root_id: str, text: str) -> str:
        if not self._api_client:
            return ""
        try:
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            body = (
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
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
            resp = self._api_client.im.v1.message.create(req)
            if resp.success():
                self._last_send_error = ""
                return resp.data.message_id or ""
            self._last_send_error = self._response_detail(resp)
            self._record_error(f"Feishu send message failed: {self._last_send_error}")
            return ""
        except Exception as exc:
            self._last_send_error = str(exc)
            self._record_error(f"Feishu send message error: {exc}")
            return ""
