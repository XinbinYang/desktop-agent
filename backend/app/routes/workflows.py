from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class WorkflowCreateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    description: str = ""
    steps: list = []
    variables: list = []


class WorkflowRunRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    variables: dict = {}


@router.get("/api/workflows")
def list_workflows_api():
    from app.workflow.engine import get_all_workflows
    return {"workflows": [w.model_dump() for w in get_all_workflows()]}


@router.get("/api/workflows/{workflow_id}")
def get_workflow_api(workflow_id: str):
    from app.workflow.engine import get_workflow
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf.model_dump()


@router.post("/api/workflows")
def create_workflow_api(req: WorkflowCreateRequest):
    import uuid
    from datetime import datetime, timezone
    from app.workflow.models import Workflow
    from app.workflow.storage import save_workflow
    wf = Workflow(
        id=f"wf-{uuid.uuid4().hex[:12]}",
        name=req.name,
        description=req.description,
        created_at=datetime.now(timezone.utc).isoformat(),
        steps=req.steps,
        variables=req.variables,
    )
    save_workflow(wf)
    return wf.model_dump()


@router.delete("/api/workflows/{workflow_id}")
def delete_workflow_api(workflow_id: str):
    from app.workflow.engine import remove_workflow
    success = remove_workflow(workflow_id)
    return {"status": "deleted" if success else "not_found"}


@router.post("/api/workflows/{workflow_id}/run")
async def run_workflow_api(workflow_id: str, req: WorkflowRunRequest):
    from app.workflow.engine import get_workflow, WorkflowExecutor
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    executor = WorkflowExecutor(wf)
    events = []
    async for event in executor.run(variables=req.variables):
        events.append(event)
    return {"events": events}
