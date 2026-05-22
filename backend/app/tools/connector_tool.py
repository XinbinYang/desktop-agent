import json
from typing import Any, Dict, Optional

from app.connectors import get_connector_manager
from app.tools.base import BaseTool, ToolResult


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _get_connector_or_error(name: str):
    manager = get_connector_manager()
    connector = manager.get(name)
    if not connector:
        return manager, None, ToolResult(error=f"Connector not found: {name}")
    return manager, connector, None


class ConnectorStatusTool(BaseTool):
    name = "connector_status"
    description = "List social platform connector status and masked configuration."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Optional connector name, e.g. discord or feishu."},
        },
    }

    async def execute(self, name: Optional[str] = None, **kwargs) -> ToolResult:
        manager = get_connector_manager()
        connectors = manager.list_connectors()
        if name:
            for connector in connectors:
                if connector["name"] == name:
                    return ToolResult(output=_json(connector))
            return ToolResult(error=f"Connector not found: {name}")
        return ToolResult(output=_json({"connectors": connectors}))


class ConnectorDoctorTool(BaseTool):
    name = "connector_doctor"
    description = "Run connector diagnostics and return actionable setup guidance."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Optional connector name, e.g. discord or feishu."},
        },
    }

    async def execute(self, name: Optional[str] = None, **kwargs) -> ToolResult:
        manager = get_connector_manager()
        try:
            result = await manager.doctor(name)
        except KeyError:
            return ToolResult(error=f"Connector not found: {name}")
        return ToolResult(output=_json(result))


class ConnectorUpdateTool(BaseTool):
    name = "connector_update"
    description = "Update a connector configuration. Sensitive values and secret changes require confirm=true."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connector name, e.g. discord or feishu."},
            "config": {"type": "object", "description": "Configuration fields to update."},
            "confirm": {
                "type": "boolean",
                "description": "Must be true when writing sensitive fields such as tokens or app secrets.",
                "default": False,
            },
        },
        "required": ["name", "config"],
    }

    async def execute(self, name: str, config: Dict[str, Any], confirm: bool = False, **kwargs) -> ToolResult:
        manager, connector, error = _get_connector_or_error(name)
        if error:
            return error
        sensitive_fields = connector.sensitive_fields()
        sensitive_update = any(
            key in sensitive_fields and value is not None and str(value).strip()
            for key, value in (config or {}).items()
        )
        if sensitive_update and not confirm:
            return ToolResult(error="confirm=true is required before writing connector secrets.")
        validation = manager.validate_config(name, config)
        if not validation["valid"]:
            return ToolResult(error=f"Missing required fields: {', '.join(validation['missing_required'])}")
        if not manager.update_config(name, config):
            return ToolResult(error=f"Connector not found: {name}")
        updated = next((c for c in manager.list_connectors() if c["name"] == name), None)
        return ToolResult(output=_json({"status": "updated", "connector": updated}))


class ConnectorStartTool(BaseTool):
    name = "connector_start"
    description = "Start a connector. Requires confirm=true because it opens an external platform connection."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connector name, e.g. discord or feishu."},
            "confirm": {"type": "boolean", "description": "Must be true to start the connector.", "default": False},
        },
        "required": ["name"],
    }

    async def execute(self, name: str, confirm: bool = False, **kwargs) -> ToolResult:
        manager, connector, error = _get_connector_or_error(name)
        if error:
            return error
        if not confirm:
            return ToolResult(error="confirm=true is required before starting an external connector.")
        ok = await manager.start(name)
        if not ok:
            return ToolResult(error=connector.last_error or connector.status_message or f"Failed to start {name}")
        return ToolResult(output=_json({"status": "started", "connector": next(c for c in manager.list_connectors() if c["name"] == name)}))


class ConnectorStopTool(BaseTool):
    name = "connector_stop"
    description = "Stop a running connector."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connector name, e.g. discord or feishu."},
        },
        "required": ["name"],
    }

    async def execute(self, name: str, **kwargs) -> ToolResult:
        manager, connector, error = _get_connector_or_error(name)
        if error:
            return error
        ok = await manager.stop(name)
        if not ok:
            return ToolResult(error=connector.last_error or connector.status_message or f"Failed to stop {name}")
        return ToolResult(output=_json({"status": "stopped", "name": name}))


class ConnectorTestTool(BaseTool):
    name = "connector_test"
    description = "Send a test message through a connector's configured notification target."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Connector name, e.g. discord or feishu."},
            "message": {"type": "string", "description": "Test message text."},
        },
        "required": ["name"],
    }

    async def execute(self, name: str, message: str = "Desktop Agent connector test message.", **kwargs) -> ToolResult:
        manager, connector, error = _get_connector_or_error(name)
        if error:
            return error
        try:
            details = await manager.send_test_message(name, message.strip() or "Desktop Agent connector test message.")
        except Exception as exc:
            return ToolResult(error=connector.last_error or str(exc))
        return ToolResult(output=_json({"status": "sent", "name": name, "details": details}))
