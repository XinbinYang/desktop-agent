from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.connectors import get_connector_manager
from app.connectors.base import CONNECTOR_AGENT_OPTIONS, CONNECTOR_TOOL_VISIBILITY_OPTIONS

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class UpdateConnectorRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    config: dict = Field(default_factory=dict)


class TestMessageRequest(BaseModel):
    message: str = "Desktop Agent connector test message."


def _operation_error_detail(name: str, fallback: str) -> dict:
    manager = get_connector_manager()
    connector = manager.get(name)
    if not connector:
        return {"message": fallback, "name": name}
    return {
        "message": connector.last_error or connector.status_message or fallback,
        "name": name,
        "status": connector.status,
        "status_message": connector.status_message,
        "last_error": connector.last_error,
        "recent_events": connector.recent_events[-5:],
    }


@router.get("")
def list_connectors():
    manager = get_connector_manager()
    return {"connectors": manager.list_connectors()}


@router.get("/{name}")
def get_connector(name: str):
    manager = get_connector_manager()
    connectors = manager.list_connectors()
    for c in connectors:
        if c["name"] == name:
            return c
    raise HTTPException(status_code=404, detail=f"Connector not found: {name}")


@router.post("/{name}/start")
async def start_connector(name: str):
    manager = get_connector_manager()
    success = await manager.start(name)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=_operation_error_detail(name, f"Failed to start connector: {name}"),
        )
    return {"status": "started", "name": name}


@router.post("/{name}/stop")
async def stop_connector(name: str):
    manager = get_connector_manager()
    success = await manager.stop(name)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=_operation_error_detail(name, f"Failed to stop connector: {name}"),
        )
    return {"status": "stopped", "name": name}


@router.post("/{name}/restart")
async def restart_connector(name: str):
    manager = get_connector_manager()
    success = await manager.restart(name)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=_operation_error_detail(name, f"Failed to restart connector: {name}"),
        )
    return {"status": "restarted", "name": name}


@router.post("/health")
async def health_check_all():
    manager = get_connector_manager()
    return await manager.check_health()


@router.post("/{name}/health")
async def health_check(name: str):
    manager = get_connector_manager()
    result = await manager.check_health(name)
    if name not in result:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    return result[name]


@router.post("/doctor")
async def doctor_all():
    manager = get_connector_manager()
    return await manager.doctor()


@router.post("/{name}/doctor")
async def doctor_connector(name: str):
    manager = get_connector_manager()
    try:
        return await manager.doctor(name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}") from exc


@router.post("/{name}/validate")
def validate_connector(name: str, req: UpdateConnectorRequest):
    manager = get_connector_manager()
    try:
        result = manager.validate_config(name, req.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}") from exc
    target_agent = req.config.get("target_agent")
    if target_agent not in (None, "") and target_agent not in CONNECTOR_AGENT_OPTIONS:
        raise HTTPException(status_code=422, detail="target_agent must be personal or coding")
    tool_visibility = req.config.get("tool_visibility")
    if tool_visibility not in (None, "") and tool_visibility not in CONNECTOR_TOOL_VISIBILITY_OPTIONS:
        raise HTTPException(status_code=422, detail="tool_visibility must be silent or debug")
    return result


@router.post("/{name}/test-message")
async def test_connector_message(name: str, req: TestMessageRequest):
    manager = get_connector_manager()
    connector = manager.get(name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    try:
        details = await manager.send_test_message(name, req.message.strip() or TestMessageRequest().message)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        detail = _operation_error_detail(name, f"Failed to send test message: {exc}")
        detail["message"] = f"Failed to send test message: {exc}"
        raise HTTPException(status_code=400, detail=detail) from exc
    return {"status": "sent", "name": name, "details": details}


@router.delete("/{name}")
async def delete_connector(name: str):
    manager = get_connector_manager()
    connector = manager.get(name)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    if connector.status == "running":
        await manager.stop(name)
    manager.unregister(name)
    return {"status": "deleted", "name": name}


@router.put("/{name}")
def update_connector(name: str, req: UpdateConnectorRequest):
    manager = get_connector_manager()
    connectors = manager.list_connectors()
    target = None
    for c in connectors:
        if c["name"] == name:
            target = c
            break
    if not target:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")

    target_agent = req.config.get("target_agent")
    if target_agent not in (None, "") and target_agent not in CONNECTOR_AGENT_OPTIONS:
        raise HTTPException(status_code=422, detail="target_agent must be personal or coding")
    tool_visibility = req.config.get("tool_visibility")
    if tool_visibility not in (None, "") and tool_visibility not in CONNECTOR_TOOL_VISIBILITY_OPTIONS:
        raise HTTPException(status_code=422, detail="tool_visibility must be silent or debug")
    try:
        validation = manager.validate_config(name, req.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}") from exc
    if not validation["valid"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Missing required fields: {', '.join(validation['missing_required'])}",
                "missing_required": validation["missing_required"],
            },
        )

    success = manager.update_config(name, req.config)
    if not success:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    return {"status": "updated", "name": name}
