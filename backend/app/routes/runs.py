from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.coding_runs import (
    apply_run,
    discard_run,
    get_run,
    list_runs,
    merge_run,
    record_event,
    worktree_status,
)

router = APIRouter()


class MergeRunRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    branch_name: Optional[str] = None


@router.get("/api/runs")
async def api_list_runs(limit: int = 100):
    return {"runs": await asyncio.to_thread(list_runs, limit=limit)}


@router.get("/api/runs/{run_id}")
async def api_get_run(run_id: str):
    run = await asyncio.to_thread(get_run, run_id)
    if not run:
        return {"error": "Run not found"}
    return run


@router.post("/api/runs/{run_id}/resume")
async def api_resume_run(run_id: str):
    run = await asyncio.to_thread(get_run, run_id)
    if not run:
        return {"error": "Run not found"}
    record_event(run_id, "resume_requested", {"run_id": run_id})
    return {
        "status": "resume_requested",
        "message": "Journal loaded. Continue the session to resume from the last completed tool boundary.",
        "run": run,
    }


@router.post("/api/runs/{run_id}/discard")
async def api_discard_run(run_id: str):
    return await asyncio.to_thread(discard_run, run_id)


@router.post("/api/runs/{run_id}/apply")
async def api_apply_run(run_id: str):
    return await asyncio.to_thread(apply_run, run_id)


@router.post("/api/runs/{run_id}/merge")
async def api_merge_run(run_id: str, req: MergeRunRequest | None = None):
    return await asyncio.to_thread(merge_run, run_id, branch_name=req.branch_name if req else None)


@router.get("/api/runs/{run_id}/worktree")
async def api_worktree_status(run_id: str):
    return await asyncio.to_thread(worktree_status, run_id)


@router.post("/api/agent/evals/run")
async def api_run_agent_evals(task_id: str = ""):
    """执行全部或单个 eval task。使用 git worktree 隔离执行。"""
    from app.eval_runner import get_eval_runner, load_manifest
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "请先打开一个项目"}}

    runner = get_eval_runner()

    if task_id:
        run = await runner.run_all(project["path"], task_ids=[task_id])
    else:
        run = await runner.run_all(project["path"])

    return {
        "run_id": run.run_id,
        "status": run.status,
        "total_tasks": run.total_tasks,
        "completed_tasks": run.completed_tasks,
        "success_rate": run.success_rate,
        "results": [r.to_dict() for r in run.results],
    }


@router.get("/api/agent/evals/status")
def api_eval_status():
    """获取当前 eval 运行状态。"""
    from app.eval_runner import get_eval_runner
    runner = get_eval_runner()
    run = runner.current_run
    if not run:
        return {"status": "idle"}
    return {
        "status": run.status,
        "total_tasks": run.total_tasks,
        "completed_tasks": run.completed_tasks,
        "success_rate": run.success_rate,
    }


@router.get("/api/agent/evals/results")
def api_eval_results():
    """获取最近一次 eval 运行结果。"""
    from app.eval_runner import get_eval_runner
    runner = get_eval_runner()
    run = runner.current_run
    if not run:
        # Fall back to manifest-only view
        from app.eval_runner import load_manifest
        tasks, err = load_manifest()
        return {
            "run_id": None,
            "status": "not_run" if not err else "error",
            "tasks": [{"id": t.id, "category": t.category, "prompt": t.prompt, "verification": t.verification} for t in tasks],
            "error": err,
        }
    return run.to_dict()


@router.get("/api/agent/evals/history")
def api_eval_history():
    """获取 eval 运行历史记录。"""
    from app.eval_runner import get_eval_runner
    return {"history": get_eval_runner().get_history()}


@router.get("/api/agent/evals/compare/{run1_id}/{run2_id}")
def api_eval_compare(run1_id: str, run2_id: str):
    """对比两次 eval 运行结果。"""
    from app.eval_runner import get_eval_runner
    comparison = get_eval_runner().compare_runs(run1_id, run2_id)
    if not comparison:
        return {"error": {"category": "not_found", "message": "找不到指定的运行记录"}}
    return comparison


@router.get("/api/agent/evals/tasks")
def api_eval_tasks():
    """获取 manifest 中定义的所有 eval task。"""
    from app.eval_runner import load_manifest
    tasks, err = load_manifest()
    if err:
        return {"error": {"category": "internal", "message": err}}
    return {
        "tasks": [
            {"id": t.id, "category": t.category, "prompt": t.prompt, "verification": t.verification}
            for t in tasks
        ]
    }
