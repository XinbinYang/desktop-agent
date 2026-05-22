import asyncio
import re
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field


class ConnectorConfig(BaseModel):
    name: str
    display_name: str
    description: str = ""
    enabled: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)


CONNECTOR_AGENT_OPTIONS = ("personal", "coding")
CONNECTOR_TOOL_VISIBILITY_OPTIONS = ("silent", "debug")


def _safe_session_part(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text.strip("._") or "unknown"


def normalize_connector_target_agent(value: Any) -> str:
    target = str(value or "personal").strip().lower()
    return target if target in CONNECTOR_AGENT_OPTIONS else "personal"


def normalize_connector_tool_visibility(value: Any) -> str:
    visibility = str(value or "silent").strip().lower()
    return visibility if visibility in CONNECTOR_TOOL_VISIBILITY_OPTIONS else "silent"


def target_agent_config_schema() -> Dict[str, Any]:
    return {
        "type": "string",
        "label": "Target Agent",
        "description": "Agent that handles messages from this connector",
        "enum": ["personal", "coding"],
        "enumLabels": {
            "personal": "Personal / Main Agent",
            "coding": "Coding Agent",
        },
        "default": "personal",
    }


def tool_visibility_config_schema() -> Dict[str, Any]:
    return {
        "type": "string",
        "label": "Tool Visibility",
        "description": "Controls whether agent tool calls are posted to this social platform.",
        "enum": ["silent", "debug"],
        "enumLabels": {
            "silent": "Silent (final replies only)",
            "debug": "Debug (show tool cards)",
        },
        "default": "silent",
    }


def mask_secret(value: Any) -> Dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"configured": False, "masked": ""}
    if len(text) <= 8:
        masked = "*" * len(text)
    else:
        masked = f"{text[:4]}...{text[-4:]}"
    return {"configured": True, "masked": masked}


class PlatformConnector(ABC):
    name: str = ""
    display_name: str = ""
    description: str = ""

    def __init__(self, config: Optional[ConnectorConfig] = None):
        self._config = config or ConnectorConfig(
            name=self.name,
            display_name=self.display_name,
            description=self.description,
        )
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._start_time: float = 0
        self._last_error: str = ""
        self._recent_events: deque[Dict[str, Any]] = deque(maxlen=30)

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @property
    @abstractmethod
    def status(self) -> str:
        """返回 "stopped" | "running" | "error" """
        ...

    @property
    def status_message(self) -> str:
        return ""

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def recent_events(self) -> list[Dict[str, Any]]:
        return list(self._recent_events)

    @property
    def uptime_seconds(self) -> float:
        if self._start_time > 0 and self.status == "running":
            return time.time() - self._start_time
        return 0

    @property
    def config(self) -> ConnectorConfig:
        return self._config

    def update_config(self, config: ConnectorConfig) -> None:
        self._config = config

    def _record_event(self, level: str, message: str, **details: Any) -> None:
        self._recent_events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "details": details,
        })

    def _record_error(self, message: str, **details: Any) -> None:
        self._last_error = message
        self._record_event("error", message, **details)

    def _clear_error(self) -> None:
        self._last_error = ""

    def get_session_id(self, user_id: str, channel_id: str = "", thread_id: str = "") -> str:
        target_agent = self.target_agent
        parts = [
            _safe_session_part(self.name),
            _safe_session_part(target_agent),
            _safe_session_part(user_id),
        ]
        if channel_id:
            parts.append(_safe_session_part(channel_id))
        session_id = "_".join(parts)
        if thread_id:
            session_id = f"{session_id}_t{_safe_session_part(thread_id)}"
        return session_id

    @property
    def target_agent(self) -> str:
        return normalize_connector_target_agent(self._config.config.get("target_agent"))

    @property
    def tool_visibility(self) -> str:
        return normalize_connector_tool_visibility(self._config.config.get("tool_visibility"))

    def resolve_agent_target(self) -> Tuple[str, str, str]:
        from app.agents.manager import AgentManager
        from app.config import get_model_for_agent

        agent_type = self.target_agent
        role_id = AgentManager.get_default_role(agent_type)
        model_id = get_model_for_agent(agent_type)
        return agent_type, role_id, model_id

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def sensitive_fields(self) -> set[str]:
        props = self.get_config_schema().get("properties", {})
        if not isinstance(props, dict):
            return set()
        return {
            key for key, prop in props.items()
            if isinstance(prop, dict) and bool(prop.get("sensitive"))
        }

    def public_config(self) -> Dict[str, Any]:
        sensitive = self.sensitive_fields()
        return {
            key: mask_secret(value) if key in sensitive else value
            for key, value in self._config.config.items()
        }

    def merge_config_update(
        self,
        config_data: Dict[str, Any],
        existing_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        existing = dict(existing_config if existing_config is not None else self._config.config)
        sensitive = self.sensitive_fields()
        for key, value in (config_data or {}).items():
            if key in sensitive:
                if isinstance(value, dict):
                    continue
                if value is None or str(value).strip() == "":
                    continue
            existing[key] = value
        return existing

    def validate_config(self, config_data: Optional[Dict[str, Any]] = None) -> list[str]:
        config = config_data if config_data is not None else self._config.config
        schema = self.get_config_schema()
        required = schema.get("required", [])
        if not isinstance(required, list):
            return []
        missing = []
        for key in required:
            value = config.get(key, "")
            if isinstance(value, dict):
                configured = bool(value.get("configured"))
                if not configured:
                    missing.append(str(key))
            elif not str(value or "").strip():
                missing.append(str(key))
        return missing

    async def send_notification(self, message: str) -> Dict[str, Any]:
        """Send an outbound notification through this connector.

        Connectors that support proactive delivery override this. The base
        implementation gives the API a clear, typed failure instead of leaking
        an AttributeError.
        """
        raise NotImplementedError(f"{self.display_name or self.name} does not support outbound notifications")

    async def doctor(self) -> Dict[str, Any]:
        missing = self.validate_config()
        health = await self.health_check()
        recommendations = []
        if missing:
            recommendations.append(f"Configure required fields: {', '.join(missing)}")
        if self.status == "error" and self.status_message:
            recommendations.append(self.status_message)
        return {
            "name": self.name,
            "display_name": self.display_name,
            "status": self.status,
            "status_message": self.status_message,
            "last_error": self.last_error,
            "missing_required": missing,
            "health": health,
            "recent_events": self.recent_events,
            "recommendations": recommendations,
        }

    def cancel_session_run(self, session_id: str) -> None:
        existing = self._running_tasks.pop(session_id, None)
        if existing and not existing.done():
            existing.cancel()

    async def health_check(self) -> Dict[str, Any]:
        return {
            "healthy": self.status == "running",
            "latency_ms": None,
            "details": "",
        }
