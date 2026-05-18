from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.collaboration.manager import add_task, cancel_run, create_run, get_run, get_task, list_events, update_task
from app.collaboration.models import TaskPacket

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])


class CreateRunRequest(BaseModel):
    session_id: str = "default"
    goal: str
    mode: str = "consult"
    project_path: str = ""
    task: Optional[TaskPacket] = None


class ResumeTaskRequest(BaseModel):
    status: str = "pending"


@router.post("/runs")
async def api_create_collaboration_run(req: CreateRunRequest):
    try:
        run = create_run(
            session_id=req.session_id,
            goal=req.goal,
            mode=req.mode,
            project_path=req.project_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task = add_task(run.run_id, req.task) if req.task else None
    return {
        "run": run.model_dump(),
        "task": task.model_dump() if task else None,
        "events": [e.model_dump() for e in list_events(run.run_id)],
    }


@router.get("/runs/{run_id}")
async def api_get_collaboration_run(run_id: str):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Collaboration run not found: {run_id}")
    tasks = [get_task(task_id) for task_id in run.task_ids]
    return {
        "run": run.model_dump(),
        "tasks": [task.model_dump() for task in tasks if task],
        "events": [e.model_dump() for e in list_events(run_id)],
    }


@router.post("/runs/{run_id}/cancel")
async def api_cancel_collaboration_run(run_id: str):
    run = cancel_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Collaboration run not found: {run_id}")
    return {
        "run": run.model_dump(),
        "events": [e.model_dump() for e in list_events(run_id)],
    }


@router.post("/tasks/{task_id}/resume")
async def api_resume_collaboration_task(task_id: str, req: ResumeTaskRequest | None = None):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Collaboration task not found: {task_id}")
    next_status = (req.status if req else "pending") or "pending"
    if next_status not in {"pending", "running", "completed", "failed", "blocked", "cancelled"}:
        raise HTTPException(status_code=400, detail=f"Invalid collaboration task status: {next_status}")
    updated = update_task(task_id, status=next_status)  # type: ignore[arg-type]
    return {
        "task": updated.model_dump() if updated else None,
        "events": [e.model_dump() for e in list_events(task.run_id)],
    }
