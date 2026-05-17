from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.connectors import get_connector_manager

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


class UpdateConnectorRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    config: dict = Field(default_factory=dict)


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
        raise HTTPException(status_code=400, detail=f"Failed to start connector: {name}")
    return {"status": "started", "name": name}


@router.post("/{name}/stop")
async def stop_connector(name: str):
    manager = get_connector_manager()
    success = await manager.stop(name)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to stop connector: {name}")
    return {"status": "stopped", "name": name}


@router.post("/{name}/restart")
async def restart_connector(name: str):
    manager = get_connector_manager()
    success = await manager.restart(name)
    if not success:
        raise HTTPException(status_code=400, detail=f"Failed to restart connector: {name}")
    return {"status": "restarted", "name": name}


@router.post("/health")
async def health_check_all():
    manager = get_connector_manager()
    return manager.check_health()


@router.post("/{name}/health")
async def health_check(name: str):
    manager = get_connector_manager()
    result = await manager.check_health(name)
    if name not in result:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    return result[name]


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

    # Validate required fields
    schema = target.get("config_schema", {})
    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [r for r in required if not req.config.get(r, "").strip()]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required fields: {', '.join(missing)}",
            )

    success = manager.update_config(name, req.config)
    if not success:
        raise HTTPException(status_code=404, detail=f"Connector not found: {name}")
    return {"status": "updated", "name": name}
