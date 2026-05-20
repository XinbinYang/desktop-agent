import asyncio
import base64
import inspect
import json
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import yaml
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import (
    AgentSession,
    SESSIONS_DIR,
    _sessions,
    _load_session_data,
    archive_session_record,
    clear_session,
    forget_session_record_cache,
    get_or_create_session,
    list_session_records,
    refresh_all_sessions_mcp_tools,
    resolve_agent_session,
    PLAN_CONTINUE_MARKER,
)
from app.config import get_model_for_agent, list_all_models, load_config
from app.credential_manager import CredentialManager
from app.errors import (
    ErrorCategory,
    auth_error,
    categorize_exception,
    error_response,
    not_found_error,
    sandbox_error,
    tool_failure_error,
    tool_not_found_error,
    validation_error,
)
from app.mcp.manager import MCP_CONFIG_PATH, get_mcp_manager
from app.project_manager import ProjectManager
from app.roles import RoleManager
from app.agents.manager import AgentManager
from app.agents.heartbeat import HeartbeatEngine
from app.runtime_paths import runtime_dir
from app.commands import get_commands
from app.collaboration.manager import cancel_run as cancel_collaboration_run, list_events as list_collaboration_events
from app.security import AUTH_HEADER, is_auth_enabled, is_valid_auth_token, resolve_current_project_file
from app.skill_authoring import (
    SkillAuthoringError,
    archive_skill as archive_user_skill,
    list_drafts as list_skill_drafts,
    publish_draft as publish_skill_draft,
    read_skill as read_user_skill,
    save_draft as save_skill_draft,
    update_draft as update_skill_draft,
    validate_skill as validate_user_skill,
)
from app.skills import SkillManager
from app.session_runtime import (
    cancel_session_runtime,
    get_session_runtime,
    session_runtime_status,
    terminate_session_runtime,
)
from app.tools import ALL_TOOLS, SAFE_DIRECT_TOOLS, get_tool, list_tool_names
from app.tools.browser_tool import close_browser_session
from app.tools.file_tool import build_file_edit_metadata
from app.tools.worker_tool import cancel_workers_for_session
from app.tools.workflow_tool import clear_recorder
from app.transcribe import get_model_info, transcribe_audio
from app.ws_connections import (
    SESSION_DELETED_CLOSE_CODE,
    SESSION_DELETED_REASON,
    allow_session_recreate,
    close_session_websockets,
    is_session_deleted,
    mark_session_deleted,
    register_session_websocket,
    session_websocket_snapshot,
    unregister_session_websocket,
)

# ç”Ÿå‘½å‘¨æœŸç®¡ç†
@asynccontextmanager
async def lifespan(app: FastAPI):
    # å¯åŠ¨æ—¶æ£€æŸ¥
    print("[Desktop Agent] Backend starting...")
    print(f"[Desktop Agent] Available tools: {list_tool_names()}")
    whisper_info = get_model_info()
    print(f"[Desktop Agent] Whisper model: {whisper_info['model_size']} (loaded: {whisper_info['loaded']}, device: {whisper_info['device']})")

    # Load plugins
    from app.plugins import get_plugin_manager
    n = get_plugin_manager().discover_and_load()
    if n > 0:
        print(f"[Desktop Agent] Loaded {n} plugin(s)")

    # Register platform connectors
    from app.connectors import get_connector_manager
    from app.connectors.discord_connector import DiscordConnector
    from app.connectors.feishu_connector import FeishuConnector
    connector_manager = get_connector_manager()
    connector_manager.register(DiscordConnector())
    connector_manager.register(FeishuConnector())
    print(f"[Desktop Agent] Registered connectors: {[c['name'] for c in connector_manager.list_connectors()]}")
    # Restore enabled connectors from saved config
    await connector_manager.start_enabled()

    yield
    print("[Desktop Agent] Backend shutting down...")
    get_plugin_manager().unload_all()
    await connector_manager.shutdown()
    await get_mcp_manager().disconnect_all()

app = FastAPI(title="Desktop Agent API", lifespan=lifespan)

# CORSï¼šå…è®¸å‰ç«¯è®¿é—®
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null", "file://"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_LOCAL_ORIGINS = frozenset({
    "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174",
    "http://localhost:5175", "null", "file://",  # packaged Electron renderer
})


def _is_local_origin(origin: str) -> bool:
    """Only allow WebSocket upgrades from known local origins."""
    return origin.lower() in _LOCAL_ORIGINS


def _collaboration_ws_event(event: Any) -> Dict[str, Any]:
    data = dict(getattr(event, "data", {}) or {})
    collab_run_id = getattr(event, "run_id", "")
    task_id = getattr(event, "task_id", "") or ""
    data.setdefault("run_id", collab_run_id)
    data.setdefault("collaboration_run_id", collab_run_id)
    if task_id:
        data.setdefault("task_id", task_id)
        data.setdefault("collaboration_task_id", task_id)
    data.setdefault("timestamp", getattr(event, "timestamp", None))
    return {"type": getattr(event, "type", "collaboration_task_update"), "data": data}


@app.middleware("http")
async def local_auth_middleware(request: Request, call_next):
    """Protect local HTTP APIs when DESKTOP_AGENT_AUTH_TOKEN is configured."""
    if request.method == "OPTIONS":
        return await call_next(request)

    if is_auth_enabled() and request.url.path.startswith("/api/"):
        token = request.headers.get(AUTH_HEADER)
        if not is_valid_auth_token(token):
            return JSONResponse(
                status_code=401,
                content=error_response(ErrorCategory.AUTH, "Unauthorized local Desktop Agent API request"),
            )

    return await call_next(request)

# Preview ç›®å½•é™æ€æ–‡ä»¶æœåŠ¡ï¼ˆç”¨äºŽ Codex ä»£ç é¢„è§ˆï¼‰
PREVIEW_DIR = runtime_dir("preview")
app.mount("/preview", StaticFiles(directory=str(PREVIEW_DIR)), name="preview")

# Route modules
from app.routes.settings import router as settings_router
from app.routes.projects import router as projects_router
from app.routes.knowledge import router as knowledge_router
from app.routes.workflows import router as workflows_router
from app.routes.runs import router as runs_router
from app.routes.agents import router as agents_router
from app.routes.connectors import router as connectors_router
from app.routes.collaboration import router as collaboration_router

app.include_router(settings_router)
app.include_router(projects_router)
app.include_router(knowledge_router)
app.include_router(workflows_router)
app.include_router(runs_router)
app.include_router(agents_router)
app.include_router(connectors_router)
app.include_router(collaboration_router)


# ====== REST API ======

class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    message: str
    session_id: str = "default"
    model_id: Optional[str] = None
    role_id: Optional[str] = None
    agent_type: Optional[str] = None
    image_base64: Optional[str] = None


class SessionResolveRequest(BaseModel):
    agent_type: str
    policy: str = "last_or_create"
    project_path: Optional[str] = None


class CompactSessionRequest(BaseModel):
    focus: Optional[str] = ""
    force: bool = False


class RewindSessionRequest(BaseModel):
    checkpoint_id: str
    retry: bool = False


def _resolve_agent_type(agent_type: Optional[str], role_id: Optional[str]) -> str:
    if agent_type in ("personal", "coding"):
        return agent_type
    return AgentManager.get_agent_type_for_role(role_id or "desktop-agent")


def _history_project_key(path: Optional[str]) -> str:
    return ProjectManager.history_key(path)


def _history_project_name(path: str) -> str:
    normalized = str(path or "").replace("\\", "/").rstrip("/")
    if not normalized:
        return "Untitled project"
    return Path(normalized).name or normalized


async def _close_browser_session_after_delete(session_id: str) -> None:
    try:
        await close_browser_session(session_id)
    except Exception as exc:
        print(f"[Session] Browser cleanup failed for {session_id}: {exc}")


def _session_activity_state(session_id: str, is_running: bool, plan_phase: Optional[str] = None) -> str:
    if is_running:
        return "running"

    phase = ""
    live = _sessions.get(session_id)
    if live is not None:
        phase = getattr(getattr(live, "plan_state", None), "phase", "") or ""
    elif plan_phase is not None:
        phase = plan_phase
    else:
        data = _load_session_data(session_id)
        plan_state = data.get("plan_state") if isinstance(data, dict) else None
        if isinstance(plan_state, dict):
            phase = str(plan_state.get("phase") or "")

    if phase in {"awaiting_decision", "awaiting_approval", "approved_waiting_build"}:
        return "needs_input"
    return "idle"


def _session_history_item(record: Dict[str, Any], connection_counts: Dict[str, int]) -> Dict[str, Any]:
    session_id = str(record.get("id") or "")
    runtime = session_runtime_status(session_id)
    is_running = bool(runtime.get("is_running"))
    item = dict(record)
    plan_phase = item.pop("_plan_phase", None)
    item["is_running"] = is_running
    item["active_connections"] = int(connection_counts.get(session_id, 0))
    item["activity_state"] = _session_activity_state(session_id, is_running, plan_phase)
    return item


def _build_session_history(include_archived: bool = False) -> Dict[str, Any]:
    current_project = ProjectManager.get_current()
    current_project_path = current_project.get("path") if current_project else None
    current_key = _history_project_key(current_project_path)
    metadata_entries = ProjectManager.list_project_history()
    metadata_by_key = {
        _history_project_key(item.get("path")): item
        for item in metadata_entries
        if _history_project_key(item.get("path"))
    }

    connection_counts = {
        str(item.get("session_id")): int(item.get("connections") or 0)
        for item in session_websocket_snapshot()
    }
    session_items: List[Dict[str, Any]] = []
    archived_counts: Dict[str, int] = {}
    for record in list_session_records(include_internal=True):
        item = _session_history_item(record, connection_counts)
        project_path = item.get("project_path")
        if item.get("archived_at"):
            if item.get("agent_type") == "coding" and project_path:
                key = _history_project_key(str(project_path))
                archived_counts[key] = archived_counts.get(key, 0) + 1
            if not include_archived:
                continue
        session_items.append(item)

    projects_by_key: Dict[str, Dict[str, Any]] = {}
    project_order: List[str] = []

    def ensure_project(
        path: Optional[str],
        source: Optional[Dict[str, Any]] = None,
        source_type: str = "session",
    ) -> Optional[Dict[str, Any]]:
        if not path:
            return None
        canonical_path = ProjectManager.canonical_project_path(path)
        key = _history_project_key(canonical_path)
        if not key:
            return None
        metadata = metadata_by_key.get(key) or {}
        is_archived = bool(metadata.get("archived_at"))
        is_removed = bool(metadata.get("removed_at"))
        if (is_archived or is_removed) and key != current_key and not include_archived:
            return None
        if key not in projects_by_key:
            project_path = ProjectManager.canonical_project_path(source.get("path") if source and source.get("path") else canonical_path)
            folder_name = _history_project_name(project_path)
            display_name = str(metadata.get("display_name") or "").strip()
            source_name = source.get("name") if source and source.get("name") else ""
            projects_by_key[key] = {
                "path": project_path,
                "canonical_path": project_path,
                "project_key": key,
                "name": display_name or source_name or folder_name,
                "display_name": display_name or None,
                "folder_name": folder_name,
                "last_opened": source.get("last_opened") if source else None,
                "is_current": key == current_key,
                "has_running": False,
                "is_pinned": bool(metadata.get("pinned_at")),
                "is_archived": is_archived,
                "archived_sessions_count": archived_counts.get(key, 0),
                "source": source_type,
                "_order": len(project_order),
                "_pinned_at": metadata.get("pinned_at") or "",
                "sessions": [],
            }
            project_order.append(key)
        elif source:
            project = projects_by_key[key]
            display_name = str(metadata.get("display_name") or "").strip()
            project["name"] = display_name or source.get("name") or project["name"]
            project["display_name"] = display_name or None
            project["folder_name"] = project.get("folder_name") or _history_project_name(project.get("path") or path)
            project["last_opened"] = source.get("last_opened") or project.get("last_opened")
            project["is_current"] = project["is_current"] or key == current_key
            project["is_pinned"] = bool(metadata.get("pinned_at"))
            project["is_archived"] = is_archived
            project["archived_sessions_count"] = archived_counts.get(key, 0)
        return projects_by_key[key]

    for project in ProjectManager.list_recent():
        ensure_project(project.get("path"), project, "recent")
    if current_project_path:
        ensure_project(current_project_path, current_project, "current")
    for metadata in metadata_entries:
        if metadata.get("pinned_at"):
            ensure_project(metadata.get("path"), metadata, "metadata")

    standalone_sessions: List[Dict[str, Any]] = []
    for item in session_items:
        project_path = item.get("project_path")
        if item.get("agent_type") == "coding" and project_path:
            project = ensure_project(str(project_path), source_type="session")
            if project is not None:
                project["sessions"].append(item)
                project["has_running"] = bool(project["has_running"] or item.get("is_running"))
            continue
        standalone_sessions.append(item)

    def session_sort_key(session: Dict[str, Any]) -> float:
        try:
            return -float(session.get("updated_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    for project in projects_by_key.values():
        project["sessions"] = sorted(project["sessions"], key=session_sort_key)
        project["archived_sessions_count"] = archived_counts.get(_history_project_key(project.get("path")), 0)

    pinned_projects = sorted(
        (project for project in projects_by_key.values() if project.get("is_pinned")),
        key=lambda project: str(project.get("_pinned_at") or ""),
        reverse=True,
    )
    regular_projects = sorted(
        (project for project in projects_by_key.values() if not project.get("is_pinned")),
        key=lambda project: int(project.get("_order") or 0),
    )
    projects = pinned_projects + regular_projects
    for project in projects:
        project.pop("_order", None)
        project.pop("_pinned_at", None)

    return {
        "current_project_path": current_project_path,
        "projects": projects,
        "standalone_sessions": standalone_sessions,
    }


class StoreCredentialRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    host: str
    username: str
    token: str

@app.get("/api/models")
def get_models():
    """èŽ·å–æ‰€æœ‰å¯ç”¨æ¨¡åž‹åˆ—è¡¨"""
    try:
        return {"models": list_all_models(), "default": get_model_for_agent("personal")}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"æ— æ³•è¯»å–æ¨¡åž‹é…ç½®æ–‡ä»¶ï¼ˆmodels.yamlï¼‰ï¼š{e}",
        ) from e

@app.get("/api/health")
def health_check():
    """Lightweight readiness endpoint for Electron startup diagnostics."""
    return {
        "status": "ok",
        "tools": len(list_tool_names()),
        "preview_dir": str(PREVIEW_DIR),
    }

@app.get("/api/tools")
def get_tools():
    """èŽ·å–æ‰€æœ‰å¯ç”¨å·¥å…·åˆ—è¡¨"""
    return {"tools": [{"name": t.name, "description": t.description} for t in ALL_TOOLS]}

@app.get("/api/roles")
def get_roles():
    """èŽ·å–æ‰€æœ‰å†…ç½®è§’è‰²åˆ—è¡¨"""
    return {"roles": RoleManager.list_roles()}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """éžæµå¼èŠå¤©ï¼ˆæµ‹è¯•ç”¨ï¼‰"""
    agent_type = _resolve_agent_type(req.agent_type, req.role_id)
    model_id = req.model_id or get_model_for_agent(agent_type)
    role_id = req.role_id or AgentManager.get_default_role(agent_type)
    try:
        session = get_or_create_session(req.session_id, model_id, role_id, agent_type=agent_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = []
    async for event in session.run(req.message, req.image_base64):
        results.append(event)

    return {"events": results}


@app.get("/api/session-history")
def get_session_history(include_archived: bool = False):
    """Return project-grouped session history with live per-session activity."""
    return _build_session_history(include_archived=include_archived)


@app.get("/api/sessions")
def list_sessions(project_path: str = "", agent_type: str = ""):
    """èŽ·å–æ‰€æœ‰ä¿å­˜çš„ä¼šè¯åˆ—è¡¨ï¼Œå¯æŒ‰é¡¹ç›®è·¯å¾„è¿‡æ»¤"""
    if agent_type and agent_type not in ("personal", "coding"):
        raise HTTPException(status_code=400, detail=f"Unknown agent_type: {agent_type}")
    return {"sessions": list_session_records(project_path=project_path, agent_type=agent_type)}


@app.get("/api/sessions/connections")
def list_session_connections():
    """Return currently accepted WebSocket connections grouped by session."""
    connections = session_websocket_snapshot()
    return {
        "connections": connections,
        "total": sum(item["connections"] for item in connections),
    }


@app.post("/api/sessions/resolve")
def resolve_session(req: SessionResolveRequest):
    """Resolve the concrete session that should back an agent navigation action."""
    try:
        resolved = resolve_agent_session(req.agent_type, req.policy, req.project_path)
        allow_session_recreate(resolved["session_id"])
        return resolved
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/sessions/{session_id}")
def get_session_snapshot(session_id: str):
    """Return a saved session snapshot for frontend history hydration."""
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        return error_response(ErrorCategory.NOT_FOUND, "Session not found")
    return session.to_snapshot()

@app.post("/api/sessions/{session_id}/clear")
async def clear_chat(session_id: str):
    session = _sessions.get(session_id)
    await terminate_session_runtime(session_id, session)
    cancel_workers_for_session(session_id)
    clear_recorder(session_id)
    clear_session(session_id)
    return {"status": "ok", "message": f"Session {session_id} cleared"}


@app.get("/api/sessions/{session_id}/context")
def get_session_context(session_id: str):
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.context_usage()


@app.get("/api/sessions/{session_id}/runtime")
def get_session_runtime_status(session_id: str):
    """Return live runtime state for one session without touching other sessions."""
    return session_runtime_status(session_id)


@app.post("/api/sessions/{session_id}/stop")
async def stop_session_runtime(session_id: str):
    """Stop only the live run owned by this session."""
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    was_running = await cancel_session_runtime(session_id, session, broadcast=True)
    cancel_workers_for_session(session_id)
    paused_plan = False
    if session is not None:
        paused_plan = session.pause_plan_build()
    return {
        "status": "ok",
        "session_id": session_id,
        "was_running": was_running,
        "paused_plan": paused_plan,
        **session_runtime_status(session_id),
    }


@app.get("/api/sessions/{session_id}/checkpoints")
def get_session_checkpoints(session_id: str):
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"checkpoints": session.build_checkpoints()}


@app.post("/api/sessions/{session_id}/compact")
async def compact_session(session_id: str, req: CompactSessionRequest):
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await session.compact_context(req.focus or "", force=req.force)
    if result is None:
        raise HTTPException(status_code=500, detail="Context compaction failed")
    return {**result, "snapshot": session.to_snapshot()}


@app.post("/api/sessions/{session_id}/rewind")
def rewind_session(session_id: str, req: RewindSessionRequest):
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    result = session.rewind_to_checkpoint(req.checkpoint_id)
    if not result:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {**result, "retry": False, "snapshot": session.to_snapshot()}


@app.post("/api/sessions/{session_id}/archive")
def archive_session(session_id: str):
    """Archive a saved session without deleting its transcript."""
    runtime = session_runtime_status(session_id)
    if runtime.get("is_running"):
        raise HTTPException(status_code=409, detail="Cannot archive a running session")
    try:
        archived = archive_session_record(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not archived:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "ok", "session": archived}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """åˆ é™¤ä¼šè¯"""
    mark_session_deleted(session_id)
    closed_connections = await close_session_websockets(
        session_id,
        code=SESSION_DELETED_CLOSE_CODE,
        reason=SESSION_DELETED_REASON,
    )
    session = _sessions.get(session_id)
    runtime_terminated = await terminate_session_runtime(session_id, session)
    cancel_workers_for_session(session_id)
    clear_recorder(session_id)
    asyncio.create_task(_close_browser_session_after_delete(session_id))
    if session_id in _sessions:
        del _sessions[session_id]
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    forget_session_record_cache(session_id)
    return {
        "status": "ok",
        "message": f"Session {session_id} deleted",
        "runtime_terminated": runtime_terminated,
        "closed_connections": closed_connections,
    }

# ---- Team shared context ----

@app.get("/api/teams/{team_id}/context")
def get_team_context(team_id: str):
    from app.teams import read_team_context
    content = read_team_context(team_id)
    return {"team_id": team_id, "content": content}

@app.post("/api/teams/{team_id}/context")
def post_team_context(team_id: str, request: Request):
    from app.teams import append_team_context
    import asyncio
    body = asyncio.run(_read_json_body(request))
    content = (body or {}).get("content", "")
    if not content:
        raise validation_error("content is required")
    append_team_context(team_id, content)
    return {"status": "ok", "team_id": team_id}

async def _read_json_body(request: Request) -> dict | None:
    try:
        return await request.json()
    except Exception:
        return None

@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """ä¸Šä¼ å›¾ç‰‡å¹¶è¿”å›ž base64"""
    content = await file.read()
    b64 = base64.b64encode(content).decode("utf-8")
    return {"filename": file.filename, "base64": b64}

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """ä¸Šä¼ éŸ³é¢‘æ–‡ä»¶ï¼Œè¿”å›ž Whisper è¯­éŸ³è½¬å½•æ–‡æœ¬ã€‚"""
    try:
        content = await file.read()
        if not content:
            return {"text": "", "error": "ç©ºéŸ³é¢‘æ–‡ä»¶"}

        # æ ¹æ®æ–‡ä»¶åæŽ¨æ–­åŽç¼€
        suffix = Path(file.filename).suffix if file.filename else ".webm"
        if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
            suffix = ".webm"

        text = await transcribe_audio(content, language="zh", suffix=suffix)
        return {"text": text, "filename": file.filename}
    except Exception as e:
        return {"text": "", "error": f"è½¬å½•å¤±è´¥: {e}"}

@app.get("/api/transcribe/info")
def transcribe_info():
    """èŽ·å– Whisper æ¨¡åž‹çŠ¶æ€ã€‚"""
    return get_model_info()

# ====== æ–‡ä»¶è¯»å– API ======

@app.get("/api/file/read")
async def read_file_api(path: str):
    """è¯»å–æ–‡ä»¶å†…å®¹ï¼Œç”¨äºŽç¼–è¾‘å™¨é¢„è§ˆã€‚path ä¸ºç»å¯¹è·¯å¾„ã€‚"""
    p, err = resolve_current_project_file(path)
    if err:
        return {"error": err}
    assert p is not None  # resolve_current_project_file returns Path when err is None

    if not p.exists():
        return {"error": f"æ–‡ä»¶ä¸å­˜åœ¨: {path}"}
    if not p.is_file():
        return {"error": f"è·¯å¾„ä¸æ˜¯æ–‡ä»¶: {path}"}

    # å®‰å…¨é™åˆ¶ï¼šé¿å…è¯»å–è¶…å¤§æ–‡ä»¶
    size = p.stat().st_size
    if size > 10 * 1024 * 1024:  # 10MB
        return {"error": f"æ–‡ä»¶è¿‡å¤§ ({size} bytes)ï¼Œæ‹’ç»è¯»å–"}

    try:
        async with aiofiles.open(p, "r", encoding="utf-8", errors="ignore") as f:
            content = await f.read()
        return {"content": content, "path": str(p)}
    except OSError as e:
        return {"error": f"æ–‡ä»¶è¯»å–é”™è¯¯: {e}"}


# ====== æ–‡ä»¶ä¿å­˜ API ======

class WriteFileRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    content: str

@app.post("/api/file/write")
async def write_file_api(req: WriteFileRequest):
    """å†™å…¥æ–‡ä»¶å†…å®¹ï¼Œç”¨äºŽç¼–è¾‘å™¨ä¿å­˜ã€‚path ä¸ºç»å¯¹è·¯å¾„ã€‚"""
    p, err = resolve_current_project_file(req.path)
    if err:
        return {"error": err}
    assert p is not None
    if p.exists() and not p.is_file():
        return {"error": f"Path is not a file: {req.path}"}
    if not p.parent.exists():
        return {"error": f"çˆ¶ç›®å½•ä¸å­˜åœ¨: {p.parent}"}

    try:
        existed = p.exists()
        old_content = ""
        if existed and p.is_file():
            try:
                old_content = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                old_content = ""
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(req.content)
        file_edit = build_file_edit_metadata(p, old_content, req.content, existed)
        return {"status": "ok", "path": str(p), "file_edit": file_edit}
    except OSError as e:
        return {"error": f"æ–‡ä»¶å†™å…¥é”™è¯¯: {e}"}


class RevertFileRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    old_content: str


@app.post("/api/file/revert")
async def revert_file_api(req: RevertFileRequest):
    """å›žé€€æ–‡ä»¶åˆ°æŒ‡å®šå†…å®¹ï¼ˆç”¨äºŽ Apply/Diff å®¡æ‰¹çš„ Reject æ“ä½œï¼‰ã€‚"""
    p, err = resolve_current_project_file(req.path)
    if err:
        return {"error": err}
    assert p is not None
    try:
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(req.old_content)
        return {"status": "ok", "path": str(p)}
    except OSError as e:
        return {"error": {"category": "internal", "message": f"æ–‡ä»¶å›žé€€å¤±è´¥: {e}"}}


# ====== Plugins API ======

@app.get("/api/plugins")
def list_plugins():
    """åˆ—å‡ºæ‰€æœ‰å·²åŠ è½½çš„æ’ä»¶ã€‚"""
    from app.plugins import get_plugin_manager
    plugins = get_plugin_manager().plugins
    return {
        "plugins": [
            {"name": p.name, "version": p.version, "description": p.description}
            for p in plugins.values()
        ],
        "count": len(plugins),
    }


@app.post("/api/plugins/reload")
def reload_plugins():
    """é‡æ–°åŠ è½½æ‰€æœ‰æ’ä»¶ã€‚"""
    from app.plugins import get_plugin_manager
    manager = get_plugin_manager()
    manager.unload_all()
    n = manager.discover_and_load()
    return {"status": "ok", "loaded": n}


# ====== Diagnostics API ======

@app.post("/api/diagnostics/run")
async def run_diagnostics_api(source: str = ""):
    """è¿è¡Œé¡¹ç›®è¯Šæ–­ï¼ˆlinter/typecheckerï¼‰ï¼Œè¿”å›žç»“æžœã€‚"""
    from app.diagnostics import run_diagnostics as run_diag, detect_linters
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "æ²¡æœ‰æ‰“å¼€çš„é¡¹ç›®"}}

    sources = [source] if source else None
    results = await run_diag(project["path"], sources)
    return {
        "results": [
            {
                "source": r.source,
                "total": r.total,
                "errors": r.errors,
                "warnings": r.warnings,
                "items": [
                    {"file_path": i.file_path, "line": i.line, "column": i.column,
                     "severity": i.severity, "message": i.message, "source": i.source}
                    for i in r.items[:200]
                ],
            }
            for r in results
        ],
    }


@app.get("/api/diagnostics/last")
def get_last_diagnostics():
    """èŽ·å–æœ€è¿‘ä¸€æ¬¡è¯Šæ–­ç»“æžœã€‚"""
    from app.diagnostics import get_last_result
    r = get_last_result()
    if not r:
        return {"total": 0, "errors": 0, "warnings": 0, "items": []}
    return {
        "source": r.source,
        "total": r.total,
        "errors": r.errors,
        "warnings": r.warnings,
        "items": [
            {"file_path": i.file_path, "line": i.line, "column": i.column,
             "severity": i.severity, "message": i.message, "source": i.source}
            for i in r.items[:200]
        ],
    }


@app.get("/api/diagnostics/linters")
def list_available_linters():
    """åˆ—å‡ºå½“å‰é¡¹ç›®å¯ç”¨çš„ linter/typecheckerã€‚"""
    from app.diagnostics import detect_linters
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"linters": []}
    return {"linters": detect_linters(project["path"])}


# ====== Test Runner API ======

@app.post("/api/tests/run")
async def run_tests_api(framework: str = "", filter: str = ""):
    """è¿è¡Œé¡¹ç›®æµ‹è¯•ï¼Œè¿”å›žç»“æžœã€‚"""
    from app.test_runner import run_and_store, detect_framework
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "æ²¡æœ‰æ‰“å¼€çš„é¡¹ç›®"}}

    run = await run_and_store(project["path"], framework or None, filter)
    return {
        "run_id": run.run_id,
        "framework": framework or detect_framework(project["path"]),
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "skipped": run.skipped,
        "errors": run.errors,
        "duration_ms": run.duration_ms,
        "results": [
            {"name": r.name, "status": r.status, "duration_ms": r.duration_ms, "file_path": r.file_path}
            for r in run.results
        ],
        "raw_output": run.raw_output[:5000],
    }


@app.get("/api/tests/last")
def get_last_test_run():
    """èŽ·å–æœ€è¿‘ä¸€æ¬¡æµ‹è¯•è¿è¡Œç»“æžœã€‚"""
    from app.test_runner import get_last_run
    run = get_last_run()
    if not run:
        return {"run_id": None, "total": 0}
    return {
        "run_id": run.run_id,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "skipped": run.skipped,
        "errors": run.errors,
        "duration_ms": run.duration_ms,
        "results": [
            {"name": r.name, "status": r.status, "duration_ms": r.duration_ms, "file_path": r.file_path}
            for r in run.results
        ],
    }


@app.get("/api/tests/framework")
def detect_test_framework():
    """æ£€æµ‹å½“å‰é¡¹ç›®çš„æµ‹è¯•æ¡†æž¶ã€‚"""
    from app.test_runner import detect_framework as detect
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"framework": None}
    return {"framework": detect(project["path"])}


# ====== Skills API ======

class SkillPreferencesRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    personal: Dict[str, bool] = Field(default_factory=dict)
    coding: Dict[str, bool] = Field(default_factory=dict)


class SkillDraftRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: str
    description: str
    body: str
    scopes: List[str] = Field(default_factory=lambda: ["personal"])
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    compatibility: str = ""
    allowed_tools: str = ""


class SkillDraftUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None
    scopes: Optional[List[str]] = None
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    compatibility: str = ""
    allowed_tools: str = ""


class SkillPublishRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    enable_for: List[str] = Field(default_factory=lambda: ["personal"])
    allow_risky: bool = False


@app.get("/api/skills")
def list_skills():
    """èŽ·å–æ‰€æœ‰å¯ç”¨çš„ Superpowers skills"""
    return SkillManager.list_skill_catalog()


@app.get("/api/skills/drafts")
def get_skill_drafts():
    """List user-created skill drafts awaiting review."""
    return {"drafts": list_skill_drafts()}


@app.post("/api/skills/drafts")
def create_skill_draft(req: SkillDraftRequest):
    """Create a user Skill draft. Drafts are inert until published."""
    try:
        draft = save_skill_draft(
            name=req.name,
            description=req.description,
            body=req.body,
            scopes=req.scopes,
            resources=req.resources,
            compatibility=req.compatibility,
            allowed_tools=req.allowed_tools,
            created_from="api",
        )
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"draft": draft}


@app.put("/api/skills/drafts/{draft_id}")
def update_skill_draft_api(draft_id: str, req: SkillDraftUpdateRequest):
    """Update a user Skill draft."""
    try:
        draft = update_skill_draft(
            draft_id,
            name=req.name,
            description=req.description,
            body=req.body,
            scopes=req.scopes,
            resources=req.resources,
            compatibility=req.compatibility,
            allowed_tools=req.allowed_tools,
        )
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"draft": draft}


@app.post("/api/skills/drafts/{draft_id}/validate")
def validate_skill_draft_api(draft_id: str):
    """Validate a user Skill draft."""
    try:
        validation = validate_user_skill(draft_id)
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"validation": validation}


@app.post("/api/skills/drafts/{draft_id}/publish")
def publish_skill_draft_api(draft_id: str, req: SkillPublishRequest):
    """Publish a validated user Skill draft and refresh the catalog."""
    try:
        skill = publish_skill_draft(draft_id, enable_for=req.enable_for, allow_risky=req.allow_risky)
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    catalog = SkillManager.list_skill_catalog()
    return {"skill": skill, **catalog}


@app.get("/api/skills/{skill_id:path}")
def read_skill_api(skill_id: str):
    """Read an Agent Skill by id, including bundled, personal, user, or draft Skills."""
    try:
        return {"skill": read_user_skill(skill_id)}
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/skills/{skill_id:path}/archive")
def archive_skill_api(skill_id: str):
    """Archive a published user Skill."""
    try:
        skill = archive_user_skill(skill_id)
    except SkillAuthoringError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    catalog = SkillManager.list_skill_catalog()
    return {"skill": skill, **catalog}


@app.put("/api/skills/preferences")
def update_skill_preferences(req: SkillPreferencesRequest):
    """Persist per-agent skill enablement preferences."""
    try:
        result = SkillManager.update_preferences(req.model_dump())
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    catalog = SkillManager.list_skill_catalog()
    return {
        **catalog,
        "ignored": result["ignored"],
    }


# ====== Commands API ======

@app.get("/api/commands")
def list_commands():
    """èŽ·å–æ‰€æœ‰å¯ç”¨çš„ slash commands"""
    return {"commands": get_commands()}


# ====== MCP API ======

class McpServerCreateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    id: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = []
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None

@app.get("/api/mcp/servers")
def list_mcp_servers():
    servers = get_mcp_manager().list_servers()
    return {"servers": [s.model_dump() for s in servers]}

@app.post("/api/mcp/servers")
async def create_mcp_server(req: McpServerCreateRequest):
    data: Dict[str, Any] = {}
    if MCP_CONFIG_PATH.exists():
        with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
            data = loaded if isinstance(loaded, dict) else {}
    if "servers" not in data:
        data["servers"] = {}
    data["servers"][req.id] = {
        "transport": req.transport,
        "command": req.command,
        "args": req.args,
        "url": req.url,
        "env": req.env,
    }
    with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    await get_mcp_manager().reload_configs()
    return {"status": "ok", "id": req.id}

@app.delete("/api/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    if not MCP_CONFIG_PATH.exists():
        return {"status": "not_found"}
    data: Dict[str, Any] = {}
    with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
        data = loaded if isinstance(loaded, dict) else {}
    if "servers" in data and server_id in data["servers"]:
        del data["servers"][server_id]
        with open(MCP_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    await get_mcp_manager().reload_configs()
    refresh_all_sessions_mcp_tools()
    return {"status": "deleted"}

@app.post("/api/mcp/servers/{server_id}/connect")
async def connect_mcp_server(server_id: str):
    success = await get_mcp_manager().connect(server_id)
    if success:
        refresh_all_sessions_mcp_tools()
    return {"connected": success}

@app.post("/api/mcp/servers/{server_id}/disconnect")
async def disconnect_mcp_server(server_id: str):
    await get_mcp_manager().disconnect(server_id)
    refresh_all_sessions_mcp_tools()
    return {"status": "disconnected"}

@app.get("/api/mcp/servers/{server_id}/tools")
def list_mcp_server_tools(server_id: str):
    server = get_mcp_manager().get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"tools": [t.model_dump() for t in server.tools]}


@app.post("/api/mcp/health")
async def mcp_health_check():
    result = await get_mcp_manager().check_health()
    if result["dead"]:
        refresh_all_sessions_mcp_tools()
    return result


# ====== å‡­æ®ç®¡ç† API ======

@app.get("/api/credentials")
def list_credentials():
    """èŽ·å–å·²å­˜å‚¨çš„ Git å‡­æ® host åˆ—è¡¨"""
    return {"hosts": CredentialManager.list_hosts(), "gcm_available": CredentialManager.has_gcm()}

@app.post("/api/credentials")
def store_credential(req: StoreCredentialRequest):
    """å­˜å‚¨ Git å‡­æ®"""
    CredentialManager.store_token(req.host, req.username, req.token)
    return {"status": "stored", "host": req.host}

@app.delete("/api/credentials/{host}")
def delete_credential(host: str):
    """åˆ é™¤æŒ‡å®š host çš„å‡­æ®"""
    CredentialManager.delete_token(host)
    return {"status": "deleted", "host": host}


# ====== WebSocketï¼ˆæ ¸å¿ƒå®žæ—¶é€šä¿¡ï¼‰ ======

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    if is_auth_enabled():
        token = websocket.headers.get(AUTH_HEADER) or websocket.query_params.get("token")
        if not is_valid_auth_token(token):
            print(f"[WS] 403 — auth token rejected for session={session_id}: "
                  f"header={'set' if websocket.headers.get(AUTH_HEADER) else 'missing'}, "
                  f"query={'set' if websocket.query_params.get('token') else 'missing'}")
            await websocket.close(code=1008, reason="Unauthorized")
            return

    # Defense in depth: only allow local origins for WS upgrade.
    origin = websocket.headers.get("origin", "")
    if origin and not _is_local_origin(origin):
        print(f"[WS] 403 — origin rejected for session={session_id}: origin={origin}")
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    if is_session_deleted(session_id):
        await websocket.accept()
        await websocket.close(code=SESSION_DELETED_CLOSE_CODE, reason=SESSION_DELETED_REASON)
        return

    await websocket.accept()
    register_session_websocket(session_id, websocket)
    current_model = get_model_for_agent("personal")
    current_role_id = "desktop-agent"
    current_agent_type = "personal"

    # å‘é€åŽ†å²ä¼šè¯æ¶ˆæ¯ï¼ˆå¦‚æžœæœ‰ï¼‰
    session = get_or_create_session(session_id, current_model, preserve_existing_model=True)
    current_model = session.model_id  # æ¢å¤å·²ä¿å­˜çš„ model
    current_role_id = session.role_id  # æ¢å¤å·²ä¿å­˜çš„ role
    current_agent_type = session.agent_type  # æ¢å¤å·²ä¿å­˜çš„ agent_type

    runtime = get_session_runtime(session_id)
    runtime_queue = runtime.subscribe()
    runtime_forward_task: "asyncio.Task | None" = None
    send_lock = asyncio.Lock()

    async def send_event(event: Dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(event)

    async def forward_runtime_events() -> None:
        while True:
            event = await runtime_queue.get()
            await send_event(event)

    try:
        # Send initial state inside the disconnect guard. In dev React StrictMode
        # can open and immediately close a probe connection before the real one.
        if any(m.get("role") != "system" for m in session.messages):
            await send_event({"type": "history_snapshot", "data": session.to_snapshot()})
            await send_event({
                "type": "status",
                "data": {
                    "status": "history_loaded",
                    "count": len([m for m in session.messages if m.get("role") != "system"]),
                },
            })

        if session.chat_mode == "plan" and session.plan_state.phase not in ("idle",):
            await send_event({"type": "plan_status", "data": session.plan_event_payload()})

        await send_event({"type": "context_usage", "data": session.context_usage()})
        if runtime.is_running:
            await send_event({
                "type": "status",
                "data": {"status": "thinking", "message": "Reconnected to running session"},
            })
        runtime_forward_task = asyncio.create_task(forward_runtime_events())

        while True:
            # æŽ¥æ”¶å‰ç«¯æ¶ˆæ¯
            data = await websocket.receive_text()
            msg = json.loads(data)

            msg_type = msg.get("type", "chat")

            if msg_type == "chat":
                user_text = msg.get("text", "")
                model_id = msg.get("model_id", current_model)
                agent_type = _resolve_agent_type(msg.get("agent_type", current_agent_type), msg.get("role_id", current_role_id))
                role_id = msg.get("role_id") or AgentManager.get_default_role(agent_type)
                image_b64 = msg.get("image_base64")
                requested_chat_mode = msg.get("chat_mode")
                thinking_intensity = msg.get("thinking_intensity")
                current_model = model_id
                current_role_id = role_id
                current_agent_type = agent_type

                try:
                    session = get_or_create_session(session_id, model_id, role_id, agent_type=agent_type)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                chat_mode = (
                    requested_chat_mode
                    if requested_chat_mode in ("agent", "plan")
                    else session.chat_mode
                )
                if runtime.is_running:
                    try:
                        item = session.queue_task_guidance(
                            user_text,
                            image_b64,
                            item_id=msg.get("guidance_id") or msg.get("id"),
                        )
                        applied = session.apply_task_guidance()
                    except ValueError as exc:
                        await send_event({"type": "error", "data": validation_error(str(exc))})
                        continue
                    await send_event({
                        "type": "task_guidance_queued",
                        "data": {
                            "item": item.model_dump(),
                            "items": session.active_task_guidance_items(),
                        },
                    })
                    if applied:
                        await send_event({
                            "type": "task_guidance_applied",
                            "data": {
                                "items": [i.model_dump() for i in applied],
                                "all_items": session.active_task_guidance_items(),
                                "auto": True,
                            },
                        })
                    continue

                async def _run_agent_events(
                    session=session,
                    user_text=user_text,
                    image_b64=image_b64,
                    chat_mode=chat_mode,
                    thinking_intensity=thinking_intensity,
                ):
                    async for event in session.run(
                        user_text,
                        image_b64,
                        chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                        thinking_intensity=thinking_intensity
                        if thinking_intensity in ("low", "medium", "high")
                        else None,
                    ):
                        yield event

                await runtime.start(session, _run_agent_events)

            elif msg_type == "queue_task_guidance":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                try:
                    item = session.queue_task_guidance(
                        str(msg.get("text") or ""),
                        msg.get("image_base64"),
                        item_id=msg.get("guidance_id") or msg.get("id"),
                    )
                    applied = session.apply_task_guidance() if runtime.is_running else []
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                await send_event({
                    "type": "task_guidance_queued",
                    "data": {
                        "item": item.model_dump(),
                        "items": session.active_task_guidance_items(),
                    },
                })
                if applied:
                    await send_event({
                        "type": "task_guidance_applied",
                        "data": {
                            "items": [i.model_dump() for i in applied],
                            "all_items": session.active_task_guidance_items(),
                            "auto": True,
                        },
                    })

            elif msg_type == "apply_task_guidance":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                applied = session.apply_task_guidance()
                await send_event({
                    "type": "task_guidance_applied",
                    "data": {
                        "items": [item.model_dump() for item in applied],
                        "all_items": session.active_task_guidance_items(),
                    },
                })
                if applied and not runtime.is_running:
                    stale = session.mark_applied_task_guidance_stale()
                    await send_event({
                        "type": "task_guidance_stale",
                        "data": {
                            "items": [item.model_dump() for item in stale],
                            "all_items": session.active_task_guidance_items(),
                        },
                    })

            elif msg_type == "delete_task_guidance":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                item_id = str(msg.get("id") or msg.get("guidance_id") or "")
                if not item_id:
                    await send_event({"type": "error", "data": validation_error("delete_task_guidance requires id")})
                    continue
                deleted = session.delete_task_guidance(item_id)
                await send_event({
                    "type": "task_guidance_deleted",
                    "data": {"id": item_id, "deleted": deleted, "items": session.active_task_guidance_items()},
                })

            elif msg_type == "clear_task_guidance":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                removed = session.clear_task_guidance()
                await send_event({
                    "type": "task_guidance_cleared",
                    "data": {
                        "items": [item.model_dump() for item in removed],
                        "all_items": session.active_task_guidance_items(),
                    },
                })

            elif msg_type == "collaborate":
                goal = str(msg.get("goal") or msg.get("text") or "").strip()
                mode = str(msg.get("mode") or "consult").strip().lower()
                if not goal:
                    await send_event({"type": "error", "data": validation_error("collaborate requires a goal")})
                    continue
                prefix = "implement" if mode == "execute" else "inspect"
                user_text = f"@coding agent {prefix}: {goal}"
                model_id = msg.get("model_id", current_model)
                role_id = AgentManager.get_default_role("personal")
                current_model = model_id
                current_role_id = role_id
                current_agent_type = "personal"
                try:
                    session = get_or_create_session(session_id, model_id, role_id, agent_type="personal")
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue

                async def _collaborate_agent_events(session=session, user_text=user_text):
                    async for event in session.run(user_text, None, chat_mode="agent"):
                        yield event

                await runtime.start(session, _collaborate_agent_events)

            elif msg_type == "collaboration_cancel":
                collab_run_id = str(msg.get("run_id") or msg.get("collaboration_run_id") or "").strip()
                if not collab_run_id:
                    await send_event({"type": "error", "data": validation_error("collaboration_cancel requires run_id")})
                    continue
                run = cancel_collaboration_run(collab_run_id)
                if not run:
                    await send_event({"type": "error", "data": not_found_error(f"Collaboration run not found: {collab_run_id}")})
                    continue
                for event in list_collaboration_events(collab_run_id):
                    await send_event(_collaboration_ws_event(event))

            elif msg_type == "handoff_agent":
                target_agent = str(msg.get("agent_type") or msg.get("to") or "coding").strip().lower()
                if target_agent not in ("personal", "coding"):
                    await send_event({"type": "error", "data": validation_error(f"Unknown agent_type: {target_agent}")})
                    continue
                project = ProjectManager.get_current()
                project_path = str(project.get("path") or "") if project else ""
                try:
                    resolved = resolve_agent_session(target_agent, "last_or_create", project_path)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                await send_event({
                    "type": "agent_switched",
                    "data": {
                        "agent_type": target_agent,
                        "name": "Personal Agent" if target_agent == "personal" else "Coding Agent",
                        "session_id": resolved.get("id"),
                        "model_id": resolved.get("model_id"),
                        "created": resolved.get("created"),
                    },
                })

            elif msg_type == "clear":
                await runtime.cancel(_sessions.get(session_id), broadcast=False)
                cancel_workers_for_session(session_id)
                clear_recorder(session_id)
                clear_session(session_id)
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await send_event({"type": "cleared"})
                await send_event({"type": "history_snapshot", "data": session.to_snapshot()})
                await send_event({"type": "context_usage", "data": session.context_usage()})

            elif msg_type == "set_chat_mode":
                mode = msg.get("chat_mode") or msg.get("chatMode") or "agent"
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if isinstance(mode, str) and session.set_session_chat_mode(mode):
                    await send_event({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})
                    await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                else:
                    await send_event({"type": "error", "data": validation_error("Invalid chat_mode")})

            elif msg_type == "set_thinking_intensity":
                intensity = msg.get("thinking_intensity") or msg.get("thinkingIntensity") or ""
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if isinstance(intensity, str) and session.set_session_thinking_intensity(intensity):
                    await send_event({
                        "type": "thinking_intensity",
                        "data": {"thinking_intensity": session.thinking_intensity},
                    })
                else:
                    await send_event({"type": "error", "data": validation_error("Invalid thinking_intensity")})

            elif msg_type == "stop":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await runtime.cancel(session, broadcast=False)
                if session.pause_plan_build():
                    await send_event({"type": "build_paused", "data": session.plan_event_payload()})
                    await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                    await send_event({"type": "todo_update", "data": {"todos": [t.model_dump() for t in session.plan_state.todos]}})
                    await send_event({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})
                await send_event({"type": "interrupted", "data": {"message": "å·²æ”¶åˆ°åœæ­¢è¯·æ±‚"}})

            elif msg_type == "retry":
                model_id = msg.get("model_id", current_model)
                agent_type = _resolve_agent_type(msg.get("agent_type", current_agent_type), msg.get("role_id", current_role_id))
                role_id = msg.get("role_id") or AgentManager.get_default_role(agent_type)
                chat_mode = msg.get("chat_mode")
                thinking_intensity = msg.get("thinking_intensity")
                current_model = model_id
                current_role_id = role_id
                current_agent_type = agent_type
                try:
                    session = get_or_create_session(session_id, model_id, role_id, agent_type=agent_type)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                if session.retry_last():
                    async def _retry_agent_events(
                        session=session,
                        chat_mode=chat_mode,
                        thinking_intensity=thinking_intensity,
                    ):
                        async for event in session.run(
                            "",
                            None,
                            chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                            thinking_intensity=thinking_intensity
                            if thinking_intensity in ("low", "medium", "high")
                            else None,
                        ):
                            yield event

                    await runtime.start(session, _retry_agent_events)
                else:
                    await send_event({"type": "error", "data": validation_error("æ²¡æœ‰å¯é‡è¯•çš„æ¶ˆæ¯")})

            elif msg_type == "approve_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.approve_plan()
                await send_event({"type": "plan_approved_waiting_build", "data": {}})
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})

            elif msg_type == "switch_model":
                model_id = msg.get("model_id", current_model)
                if model_id and model_id != current_model:
                    current_model = model_id
                    session = get_or_create_session(session_id, model_id, current_role_id, agent_type=current_agent_type)
                    session.router = type(session.router)(model_id)  # Rebuild ModelRouter
                    session.model_id = model_id
                    session._agent_models[current_agent_type] = model_id
                    session._refresh_system_prompt()
                    session._save()
                    await send_event({
                        "type": "model_switched",
                        "data": {"model_id": model_id, "agent_type": current_agent_type},
                    })

            elif msg_type == "reject_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.reject_plan()
                await send_event({"type": "plan_rejected", "data": {}})
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})

            elif msg_type == "compact":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                result = await session.compact_context(
                    focus=str(msg.get("focus") or ""),
                    force=bool(msg.get("force", False)),
                )
                if result:
                    await send_event({
                        "type": "compacted",
                        "data": {
                            **result,
                            "message_count": len(session.messages),
                            "source": msg.get("source") or "websocket",
                        },
                    })
                    await send_event({"type": "history_snapshot", "data": session.to_snapshot()})
                    await send_event({"type": "context_usage", "data": session.context_usage()})
                else:
                    await send_event({
                        "type": "error",
                        "data": validation_error("å¯¹è¯æ¶ˆæ¯ä¸è¶³ï¼Œæ— éœ€åŽ‹ç¼©ï¼ˆè‡³å°‘éœ€è¦ 15 æ¡æ¶ˆæ¯ï¼‰"),
                    })

            elif msg_type == "context":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await send_event({"type": "context_usage", "data": session.context_usage()})

            elif msg_type == "rewind":
                model_id = msg.get("model_id", current_model)
                agent_type = _resolve_agent_type(msg.get("agent_type", current_agent_type), msg.get("role_id", current_role_id))
                role_id = msg.get("role_id") or AgentManager.get_default_role(agent_type)
                chat_mode = msg.get("chat_mode")
                thinking_intensity = msg.get("thinking_intensity")
                checkpoint_id = str(msg.get("checkpoint_id") or msg.get("checkpointId") or "")
                current_model = model_id
                current_role_id = role_id
                current_agent_type = agent_type
                try:
                    session = get_or_create_session(session_id, model_id, role_id, agent_type=agent_type)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                result = session.rewind_to_checkpoint(checkpoint_id)
                if not result:
                    await send_event({"type": "error", "data": validation_error("Checkpoint not found")})
                    continue
                await send_event({"type": "rewound", "data": result})
                await send_event({"type": "history_snapshot", "data": session.to_snapshot()})
                await send_event({"type": "context_usage", "data": session.context_usage()})
                if bool(msg.get("retry", True)):
                    async def _rewind_retry_agent_events(
                        session=session,
                        chat_mode=chat_mode,
                        thinking_intensity=thinking_intensity,
                    ):
                        async for event in session.run(
                            "",
                            None,
                            chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                            thinking_intensity=thinking_intensity
                            if thinking_intensity in ("low", "medium", "high")
                            else None,
                        ):
                            yield event

                    await runtime.start(session, _rewind_retry_agent_events)

            elif msg_type == "build_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                already_executing = session.plan_state.phase == "executing" and session.plan_state.approved
                if not session.build_plan():
                    restored = session.restore_plan_state_snapshot(msg.get("plan_state") or {})
                    if not restored or not session.build_plan():
                        await send_event({"type": "error", "data": validation_error("No plan is ready to build. Wait for the plan draft first.")})
                        continue
                    already_executing = session.plan_state.phase == "executing" and session.plan_state.approved

                await send_event({"type": "build_started", "data": {}})
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                await send_event({"type": "todo_update", "data": {"todos": [t.model_dump() for t in session.plan_state.todos]}})
                # Sync frontend mode: Build auto-switches to agent mode.
                await send_event({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})

                if already_executing and runtime.is_running:
                    continue

                async def _plan_continue_agent_events(session=session):
                    async for event in session.run(PLAN_CONTINUE_MARKER, None):
                        yield event

                await runtime.start(session, _plan_continue_agent_events)

            elif msg_type == "pause_build":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await runtime.cancel(session, broadcast=False)
                if not session.pause_plan_build():
                    await send_event({"type": "error", "data": validation_error("No active Build is running.")})
                    continue
                await send_event({"type": "build_paused", "data": session.plan_event_payload()})
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                await send_event({"type": "todo_update", "data": {"todos": [t.model_dump() for t in session.plan_state.todos]}})
                await send_event({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})

            elif msg_type in ("end_build", "exit_build"):
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await runtime.cancel(session, broadcast=False)
                if not session.exit_plan_build():
                    await send_event({"type": "error", "data": validation_error("No active or paused Build to end.")})
                    continue
                await send_event({"type": "build_ended", "data": session.plan_event_payload()})
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                await send_event({"type": "todo_update", "data": {"todos": [t.model_dump() for t in session.plan_state.todos]}})
                await send_event({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})

            elif msg_type == "update_plan_decision":
                qid = msg.get("question_id") or msg.get("questionId")
                selected = msg.get("selected") or []
                if not isinstance(selected, list):
                    selected = [selected] if selected is not None else []
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if qid is not None:
                    session.update_plan_decision(str(qid), [str(s) for s in selected])
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                if session.plan_state.phase == "awaiting_approval":
                    await send_event({
                        "type": "plan_draft",
                        "data": {
                            "goal": session.plan_state.goal,
                            "draft": session.plan_state.draft,
                            "structured_plan": session.plan_state.structured_plan.model_dump() if session.plan_state.structured_plan else None,
                            "todos": [t.model_dump() for t in session.plan_state.todos],
                            "phase": session.plan_state.phase,
                            "pending_clarification": session.plan_state.pending_clarification,
                        },
                    })
                elif session.plan_state.phase == "planning":
                    # All decisions collected â€” feed back to LLM for plan_write_draft.
                    async def _plan_clarify_agent_events(session=session):
                        async for event in session.run("", None):
                            yield event

                    await runtime.start(session, _plan_clarify_agent_events)

            elif msg_type == "submit_plan_decisions":
                answers = msg.get("answers") or []
                if not isinstance(answers, list):
                    answers = []
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.submit_plan_decisions([a for a in answers if isinstance(a, dict)])
                await send_event({"type": "plan_status", "data": session.plan_event_payload()})
                if session.plan_state.phase == "awaiting_approval":
                    await send_event({
                        "type": "plan_draft",
                        "data": {
                            "goal": session.plan_state.goal,
                            "draft": session.plan_state.draft,
                            "structured_plan": session.plan_state.structured_plan.model_dump() if session.plan_state.structured_plan else None,
                            "todos": [t.model_dump() for t in session.plan_state.todos],
                            "phase": session.plan_state.phase,
                            "pending_clarification": session.plan_state.pending_clarification,
                        },
                    })
                elif session.plan_state.phase == "planning":
                    async def _plan_submit_agent_events(session=session):
                        async for event in session.run("", None):
                            yield event

                    await runtime.start(session, _plan_submit_agent_events)

            elif msg_type == "switch_agent":
                agent_type = msg.get("agent_type", "personal")
                if agent_type not in ("personal", "coding"):
                    await send_event({"type": "error", "data": {"message": f"Unknown agent_type: {agent_type}"}})
                    continue
                try:
                    session = get_or_create_session(session_id, current_model, role_id=current_role_id, agent_type=agent_type)
                    session.switch_agent(agent_type)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                current_role_id = session.role_id
                current_agent_type = agent_type
                current_model = session.model_id
                await send_event({
                    "type": "agent_switched",
                    "data": {
                        "agent_type": agent_type,
                        "name": "Personal Agent" if agent_type == "personal" else "Coding Agent",
                        "model_id": session.model_id,
                        "thinking_intensity": session.thinking_intensity,
                    },
                })

            elif msg_type == "switch_role":
                role_id = msg.get("role_id", current_role_id)
                agent_type = AgentManager.get_agent_type_for_role(role_id)
                try:
                    session = get_or_create_session(session_id, current_model, role_id=role_id, agent_type=agent_type)
                    session.switch_role(role_id)
                except ValueError as exc:
                    await send_event({"type": "error", "data": validation_error(str(exc))})
                    continue
                current_role_id = role_id
                current_agent_type = agent_type
                await send_event({
                    "type": "agent_switched",
                    "data": {"agent_type": agent_type, "name": "Personal Agent" if agent_type == "personal" else "Coding Agent"},
                })

            elif msg_type == "switch_project":
                project_path = msg.get("path")
                if project_path:
                    try:
                        # open_project shells out to git up to 4Ã— with 5s timeouts each;
                        # offloading keeps the WS event loop responsive for parallel sessions.
                        project = await asyncio.to_thread(ProjectManager.open_project, project_path)
                        await asyncio.to_thread(CredentialManager.configure_gcm, project_path)
                        await send_event({"type": "project_changed", "data": {"project": project}})
                    except ValueError as e:
                        await send_event({"type": "error", "data": validation_error(str(e))})
                else:
                    ProjectManager.close_project()
                    await send_event({"type": "project_changed", "data": {"project": None}})

            elif msg_type == "set_team":
                team_id = msg.get("team_id") or None
                team_name = msg.get("team_name", "")
                session.set_team(team_id, team_name)
                await send_event({"type": "team_set", "data": {"team_id": team_id, "team_name": team_name}})

            elif msg_type == "tool_direct":
                # å‰ç«¯ç›´æŽ¥è°ƒç”¨å·¥å…·ï¼ˆä»…é™ SAFE_DIRECT_TOOLS ç™½åå•ä¸­çš„åªè¯»/å¯è§æ“ä½œï¼‰
                tool_name = msg.get("tool_name")
                tool_args = msg.get("args", {})
                if tool_name not in SAFE_DIRECT_TOOLS:
                    if tool_name in list_tool_names():
                        await send_event({
                            "type": "error",
                            "data": sandbox_error(f"Tool not allowed via direct invocation: {tool_name}"),
                        })
                    else:
                        await send_event({"type": "error", "data": tool_not_found_error(tool_name)})
                    continue

                tool = get_tool(tool_name)
                try:
                    tool_params = inspect.signature(tool.execute).parameters
                    if "session_id" in tool_params and "session_id" not in tool_args:
                        tool_args["session_id"] = session_id
                    result = await tool.execute(**tool_args)
                except Exception as e:
                    failure = tool_failure_error(f"Tool execution failed: {e}", tool_name)
                    await send_event({
                        "type": "tool_result",
                        "data": {
                            "name": tool_name, "args": tool_args, "output": "",
                            "error": failure.get("message", str(e)),
                            "image": None,
                        }
                    })
                    continue
                metadata = result.metadata or {}
                if metadata.get("automation_snapshot"):
                    await send_event({
                        "type": "automation_snapshot",
                        "data": metadata["automation_snapshot"],
                    })
                if metadata.get("automation_action"):
                    await send_event({
                        "type": "automation_action",
                        "data": metadata["automation_action"],
                    })
                if metadata.get("automation_trace"):
                    await send_event({
                        "type": "automation_trace",
                        "data": metadata["automation_trace"],
                    })
                if metadata.get("automation_replay_status"):
                    await send_event({
                        "type": "automation_replay_status",
                        "data": metadata["automation_replay_status"],
                    })
                await send_event({
                    "type": "tool_result",
                    "data": {"name": tool_name, "args": tool_args, "output": result.output, "error": result.error, "image": result.base64_image}
                })

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {session_id}")
        # A WebSocket disconnect is often just renderer reload/HMR/reconnect.
        # Do not cancel the session-owned runtime here.
        if not runtime.is_running:
            try:
                asyncio.create_task(HeartbeatEngine.on_session_end(session.messages, session_id))
            except Exception:
                pass
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await send_event({"type": "error", "data": categorize_exception(e)})
        except Exception:
            pass
    finally:
        runtime.unsubscribe(runtime_queue)
        if runtime_forward_task and not runtime_forward_task.done():
            runtime_forward_task.cancel()
            with suppress(asyncio.CancelledError):
                await runtime_forward_task
        unregister_session_websocket(session_id, websocket)
