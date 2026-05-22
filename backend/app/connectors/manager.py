import json
import logging
import os
import asyncio
from typing import Any, Dict, List, Optional

from app.connectors.base import ConnectorConfig, PlatformConnector, mask_secret
from app.runtime_paths import runtime_dir

logger = logging.getLogger(__name__)

CONNECTORS_DIR = runtime_dir("connectors")
CONNECTORS_CONFIG_FILE = CONNECTORS_DIR / "connectors.json"
MAX_STARTUP_RETRY_COUNT = 5  # Maximum consecutive failures before giving up on auto-start


class ConnectorManager:
    """管理所有外部平台连接器的生命周期。"""

    def __init__(self):
        self._connectors: Dict[str, PlatformConnector] = {}
        self._configs: Dict[str, ConnectorConfig] = {}
        self._startup_failures: Dict[str, int] = {}
        self._load_configs()

    def _load_configs(self) -> None:
        self._configs = {}
        CONNECTORS_DIR.mkdir(parents=True, exist_ok=True)
        if not CONNECTORS_CONFIG_FILE.exists():
            return
        try:
            data = json.loads(CONNECTORS_CONFIG_FILE.read_text(encoding="utf-8"))
            for name, cfg_data in data.get("connectors", {}).items():
                self._configs[name] = ConnectorConfig(
                    name=cfg_data.get("name", name),
                    display_name=cfg_data.get("display_name", name),
                    description=cfg_data.get("description", ""),
                    enabled=cfg_data.get("enabled", False),
                    config=cfg_data.get("config", {}),
                )
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[ConnectorManager] Failed to load configs: %s", e)

    def _save_configs(self) -> None:
        CONNECTORS_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "connectors": {
                name: cfg.model_dump()
                for name, cfg in self._configs.items()
            }
        }
        try:
            tmp = CONNECTORS_CONFIG_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, CONNECTORS_CONFIG_FILE)
        except OSError as e:
            logger.warning("[ConnectorManager] Failed to save configs: %s", e)

    def register(self, connector: PlatformConnector) -> None:
        name = connector.name
        if name in self._configs:
            connector.update_config(self._configs[name])
        else:
            self._configs[name] = connector.config
        self._connectors[name] = connector
        self._save_configs()

    def unregister(self, name: str) -> None:
        if name in self._configs:
            del self._configs[name]
            self._save_configs()
        self._connectors.pop(name, None)
        self._startup_failures.pop(name, None)

    def update_config(self, name: str, config_data: Dict[str, Any]) -> bool:
        if name not in self._configs:
            return False
        existing = self._configs[name]
        connector = self._connectors.get(name)
        if connector:
            existing.config = connector.merge_config_update(config_data, existing.config)
        else:
            existing.config = dict(config_data)
        existing.enabled = bool(config_data.get("enabled", existing.enabled))
        self._save_configs()
        if connector:
            connector.update_config(existing)
        return True

    async def start(self, name: str) -> bool:
        connector = self._connectors.get(name)
        if not connector:
            logger.warning("[ConnectorManager] Connector not registered: %s", name)
            return False
        try:
            await connector.start()
            cfg = self._configs.get(name)
            if cfg:
                cfg.enabled = True
                self._save_configs()
            self._startup_failures.pop(name, None)
            return True
        except Exception as e:
            if hasattr(connector, "_record_error"):
                connector._record_error(f"Failed to start connector: {e}")
            logger.error("[ConnectorManager] Failed to start %s: %s", name, e)
            return False

    async def stop(self, name: str) -> bool:
        connector = self._connectors.get(name)
        if not connector:
            return False
        try:
            await connector.stop()
            cfg = self._configs.get(name)
            if cfg:
                cfg.enabled = False
                self._save_configs()
            return True
        except Exception as e:
            logger.error("[ConnectorManager] Failed to stop %s: %s", name, e)
            return False

    async def restart(self, name: str) -> bool:
        stopped = await self.stop(name)
        if not stopped and name in self._connectors:
            pass  # Try starting anyway
        await asyncio.sleep(0.5)
        return await self.start(name)

    async def start_enabled(self) -> None:
        """Auto-start connectors that were enabled in saved config.
        Skips connectors that have failed too many times consecutively."""
        for name in list(self._configs.keys()):
            cfg = self._configs[name]
            if not cfg.enabled:
                continue

            failures = self._startup_failures.get(name, 0)
            if failures >= MAX_STARTUP_RETRY_COUNT:
                logger.warning(
                    "[ConnectorManager] Skipping auto-start for %s (failed %d times)",
                    name, failures,
                )
                continue

            try:
                ok = await self.start(name)
                if ok:
                    logger.info("[ConnectorManager] Auto-started: %s", name)
                else:
                    self._startup_failures[name] = failures + 1
            except Exception as e:
                logger.warning("[ConnectorManager] Auto-start failed for %s: %s", name, e)
                self._startup_failures[name] = failures + 1

    def get(self, name: str) -> Optional[PlatformConnector]:
        return self._connectors.get(name)

    def list_connectors(self) -> List[Dict[str, Any]]:
        result = []
        for name, cfg in self._configs.items():
            connector = self._connectors.get(name)
            status = connector.status if connector else "stopped"
            status_msg = ""
            uptime = 0.0
            last_error = ""
            recent_events: list[Dict[str, Any]] = []
            config_payload = cfg.config
            if connector:
                status_msg = connector.status_message
                uptime = connector.uptime_seconds
                last_error = connector.last_error
                recent_events = connector.recent_events
                config_payload = connector.public_config()
            result.append({
                "name": name,
                "display_name": cfg.display_name,
                "description": cfg.description,
                "status": status,
                "status_message": status_msg,
                "last_error": last_error,
                "recent_events": recent_events,
                "enabled": cfg.enabled,
                "uptime_seconds": uptime,
                "config": config_payload,
                "config_schema": connector.get_config_schema() if connector else {},
            })
        return result

    def validate_config(self, name: str, config_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        connector = self._connectors.get(name)
        if not connector:
            raise KeyError(name)
        existing = self._configs.get(name)
        base = existing.config if existing else connector.config.config
        merged = connector.merge_config_update(config_data or {}, base) if config_data is not None else base
        missing = connector.validate_config(merged)
        return {
            "valid": not missing,
            "missing_required": missing,
            "config": connector.public_config() if config_data is None else {
                key: (mask_secret(value) if key in connector.sensitive_fields() else value)
                for key, value in merged.items()
            },
        }

    async def check_health(self, name: Optional[str] = None) -> Dict[str, Any]:
        """Health check for a specific or all connectors."""
        if name:
            connector = self._connectors.get(name)
            if not connector:
                return {name: {"healthy": False, "details": "Not found"}}
            result = await connector.health_check()
            return {name: result}

        results = {}
        for n, connector in self._connectors.items():
            try:
                results[n] = await connector.health_check()
            except Exception as e:
                results[n] = {"healthy": False, "details": str(e)}
        return results

    async def doctor(self, name: Optional[str] = None) -> Dict[str, Any]:
        if name:
            connector = self._connectors.get(name)
            if not connector:
                raise KeyError(name)
            return await connector.doctor()

        results = {}
        for n, connector in self._connectors.items():
            try:
                results[n] = await connector.doctor()
            except Exception as e:
                results[n] = {
                    "name": n,
                    "status": "error",
                    "last_error": str(e),
                    "recommendations": [str(e)],
                }
        return results

    async def send_test_message(self, name: str, message: str) -> Dict[str, Any]:
        connector = self._connectors.get(name)
        if not connector:
            raise KeyError(name)
        return await connector.send_notification(message)

    async def shutdown(self) -> None:
        for name in list(self._connectors.keys()):
            try:
                await self.stop(name)
            except Exception as e:
                logger.warning("[ConnectorManager] Error stopping %s during shutdown: %s", name, e)
        self._connectors.clear()

_connector_manager: Optional[ConnectorManager] = None


def get_connector_manager() -> ConnectorManager:
    global _connector_manager
    if _connector_manager is None:
        _connector_manager = ConnectorManager()
    return _connector_manager
