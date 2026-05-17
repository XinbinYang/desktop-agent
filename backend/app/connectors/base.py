import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ConnectorConfig(BaseModel):
    name: str
    display_name: str
    description: str = ""
    enabled: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)


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
    def uptime_seconds(self) -> float:
        if self._start_time > 0 and self.status == "running":
            return time.time() - self._start_time
        return 0

    @property
    def config(self) -> ConnectorConfig:
        return self._config

    def update_config(self, config: ConnectorConfig) -> None:
        self._config = config

    def get_session_id(self, user_id: str, channel_id: str = "") -> str:
        if channel_id:
            return f"{self.name}:{user_id}:{channel_id}"
        return f"{self.name}:{user_id}"

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
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
