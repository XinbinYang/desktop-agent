"""Agent configuration REST API — Dual-Agent architecture (Personal + Coding)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.manager import AgentManager
from app.agents.dream import DreamEngine
from app.agents.evolution import EvolutionEngine
from app.agents.learnings import LearningsEngine
from app.config import get_model_for_agent, get_thinking_intensity_for_agent, load_config
from app.project_manager import ProjectManager
from app.tools import get_tool_schemas

router = APIRouter(prefix="/api/agents", tags=["agents"])


class WorkspaceFileSave(BaseModel):
    content: str


class MoodUpdate(BaseModel):
    mood: str  # "positive" | "neutral" | "negative"


@router.get("")
async def list_agents():
    """List all agent types with status."""
    cfg = load_config()
    project = ProjectManager.get_current()
    recent_runs: List[Dict[str, Any]] = []
    try:
        from app.coding_runs import list_runs as list_coding_runs
        recent_runs = list_coding_runs(limit=5)
    except Exception:
        recent_runs = []

    agents: List[Dict[str, Any]] = []
    for agent in AgentManager.list_agents():
        agent_type = agent["type"]
        tool_schemas = get_tool_schemas(agent_type=agent_type)
        enriched = {
            **agent,
            "default_role": AgentManager.get_default_role(agent_type),
            "model_id": get_model_for_agent(agent_type),
            "thinking_intensity": get_thinking_intensity_for_agent(agent_type),
            "tool_profile": {
                "tool_count": len(tool_schemas),
                "mode": "focused_coding" if agent_type == "coding" else "desktop_personal",
            },
            "workspace": {
                "files": AgentManager.list_workspace_files(agent_type),
            },
        }
        if agent_type == "personal":
            enriched["bootstrap"] = {"bootstrapped": AgentManager.is_bootstrapped()}
        if agent_type == "coding":
            enriched["project"] = project
            enriched["coding_config"] = cfg.coding_agent.model_dump()
            enriched["recent_runs"] = recent_runs
        agents.append(enriched)

    return {"agents": agents}


@router.get("/{agent_type}/files")
async def list_workspace_files(agent_type: str):
    """List all files in an agent's workspace directory."""
    if agent_type not in AgentManager.BUILTIN_AGENTS and agent_type != "_shared":
        raise HTTPException(status_code=404, detail=f"Agent type not found: {agent_type}")
    return {"files": AgentManager.list_workspace_files(agent_type)}


@router.get("/{agent_type}/files/{filename:path}")
async def get_workspace_file(agent_type: str, filename: str):
    """Read a workspace file's content."""
    if agent_type not in AgentManager.BUILTIN_AGENTS and agent_type != "_shared":
        raise HTTPException(status_code=404, detail=f"Agent type not found: {agent_type}")
    content = AgentManager.load_workspace_file(agent_type, filename)
    if not content and not (AgentManager._resolve_path(agent_type, filename).exists()):
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return {"filename": filename, "content": content}


@router.put("/{agent_type}/files/{filename:path}")
async def save_workspace_file(agent_type: str, filename: str, body: WorkspaceFileSave):
    """Save content to a workspace file."""
    if agent_type not in AgentManager.BUILTIN_AGENTS and agent_type != "_shared":
        raise HTTPException(status_code=404, detail=f"Agent type not found: {agent_type}")
    ok = AgentManager.save_workspace_file(agent_type, filename, body.content)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save file")
    return {"status": "ok", "filename": filename}


# ── Personal Agent specific endpoints ──


@router.get("/personal/diaries")
async def list_diaries():
    """List recent diary entries."""
    mem_dir = AgentManager._memory_dir()
    if not mem_dir.exists():
        return {"diaries": []}

    diaries: List[Dict[str, Any]] = []
    for f in sorted(mem_dir.glob("*.md"), reverse=True):
        try:
            diaries.append({
                "date": f.stem,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
        except OSError:
            pass
    return {"diaries": diaries[:30]}


@router.get("/personal/diaries/{date}")
async def get_diary(date: str):
    """Read a specific diary entry."""
    diary_path = AgentManager._memory_dir() / f"{date}.md"
    if not diary_path.exists():
        raise HTTPException(status_code=404, detail=f"Diary not found: {date}")
    try:
        content = diary_path.read_text(encoding="utf-8")
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to read diary")
    return {"date": date, "content": content}


@router.get("/personal/mood")
async def get_mood():
    """Get current mood state."""
    mood_path = AgentManager._memory_dir() / "mood.json"
    if not mood_path.exists():
        return {"current": "neutral", "baseline": "positive", "history": []}
    try:
        return json.loads(mood_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"current": "neutral", "baseline": "positive", "history": []}


@router.get("/personal/dreams")
async def get_dreams():
    """Get dream diary (DREAMS.md)."""
    path = AgentManager._personal_dir() / "DREAMS.md"
    if not path.exists():
        return {"content": ""}
    try:
        return {"content": path.read_text(encoding="utf-8")}
    except OSError:
        return {"content": ""}


@router.post("/personal/dream/trigger")
async def trigger_dream():
    """Manually trigger a DREAM consolidation cycle."""
    result = await DreamEngine.run()
    return result


@router.post("/personal/evolve/trigger")
async def trigger_evolution():
    """Manually trigger a self-evolution cycle."""
    result = await EvolutionEngine.run_evolution_cycle()
    return result


@router.post("/personal/bootstrap/reset")
async def reset_bootstrap():
    """Reset the bootstrap process — re-creates BOOTSTRAP.md for re-onboarding."""
    ok = AgentManager.reset_bootstrap()
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to reset bootstrap")
    return {"status": "ok", "message": "BOOTSTRAP.md re-created. Agent will re-enter onboarding on next session."}


@router.get("/personal/bootstrap/status")
async def bootstrap_status():
    """Check if bootstrap onboarding is complete."""
    return {"bootstrapped": AgentManager.is_bootstrapped()}
    result = await EvolutionEngine.run_evolution_cycle()
    return result


@router.get("/personal/learnings")
async def get_learnings():
    """Get learnings, errors, and feature requests."""
    result: Dict[str, Any] = {}

    for name in ["LEARNINGS", "ERRORS", "FEATURE_REQUESTS"]:
        key = name.lower()
        path = AgentManager._personal_dir() / ".learnings" / f"{name}.md"
        if path.exists():
            try:
                result[key] = path.read_text(encoding="utf-8")
            except OSError:
                result[key] = ""
        else:
            result[key] = ""

    # Add promotable learnings
    result["promotable"] = LearningsEngine.get_learnings_promotable()

    return result


@router.get("/personal/skills")
async def get_skills():
    """Get crystallized skills with stats."""
    return {"skills": EvolutionEngine.list_skills()}


@router.get("/personal/archive")
async def get_archives():
    """Get archive snapshots."""
    return {"archives": EvolutionEngine.list_archives()}
