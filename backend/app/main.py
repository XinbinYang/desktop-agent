import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
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
    clear_session,
    get_or_create_session,
    list_session_records,
    refresh_all_sessions_mcp_tools,
    resolve_agent_session,
    PLAN_CONTINUE_MARKER,
)
from app.config import list_all_models, load_config
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
from app.security import AUTH_HEADER, is_auth_enabled, is_valid_auth_token, resolve_current_project_file
from app.skills import SkillManager
from app.tools import ALL_TOOLS, SAFE_DIRECT_TOOLS, get_tool, list_tool_names
from app.tools.file_tool import build_file_edit_metadata
from app.tools.worker_tool import reset_worker_event_callback, set_worker_event_callback
from app.transcribe import get_model_info, transcribe_audio

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时检查
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

# CORS：允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_LOCAL_ORIGINS = frozenset({
    "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:5174",
    "http://localhost:5175", "null",  # null = file:// (Electron renderer)
})


def _is_local_origin(origin: str) -> bool:
    """Only allow WebSocket upgrades from known local origins."""
    return origin.lower() in _LOCAL_ORIGINS


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

# Preview 目录静态文件服务（用于 Codex 代码预览）
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

app.include_router(settings_router)
app.include_router(projects_router)
app.include_router(knowledge_router)
app.include_router(workflows_router)
app.include_router(runs_router)
app.include_router(agents_router)
app.include_router(connectors_router)


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

class StoreCredentialRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    host: str
    username: str
    token: str

@app.get("/api/models")
def get_models():
    """获取所有可用模型列表"""
    try:
        return {"models": list_all_models(), "default": load_config().settings.default_model}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法读取模型配置文件（models.yaml）：{e}",
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
    """获取所有可用工具列表"""
    return {"tools": [{"name": t.name, "description": t.description} for t in ALL_TOOLS]}

@app.get("/api/roles")
def get_roles():
    """获取所有内置角色列表"""
    return {"roles": RoleManager.list_roles()}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """非流式聊天（测试用）"""
    model_id = req.model_id or load_config().settings.default_model
    agent_type = _resolve_agent_type(req.agent_type, req.role_id)
    role_id = req.role_id or AgentManager.get_default_role(agent_type)
    try:
        session = get_or_create_session(req.session_id, model_id, role_id, agent_type=agent_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    results = []
    async for event in session.run(req.message, req.image_base64):
        results.append(event)

    return {"events": results}

@app.get("/api/sessions")
def list_sessions(project_path: str = "", agent_type: str = ""):
    """获取所有保存的会话列表，可按项目路径过滤"""
    if agent_type and agent_type not in ("personal", "coding"):
        raise HTTPException(status_code=400, detail=f"Unknown agent_type: {agent_type}")
    return {"sessions": list_session_records(project_path=project_path, agent_type=agent_type)}


@app.post("/api/sessions/resolve")
def resolve_session(req: SessionResolveRequest):
    """Resolve the concrete session that should back an agent navigation action."""
    try:
        return resolve_agent_session(req.agent_type, req.policy, req.project_path)
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
def clear_chat(session_id: str):
    clear_session(session_id)
    return {"status": "ok", "message": f"Session {session_id} cleared"}


@app.get("/api/sessions/{session_id}/context")
def get_session_context(session_id: str):
    session = _sessions.get(session_id) or AgentSession.load(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.context_usage()


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

@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    """删除会话"""
    if session_id in _sessions:
        del _sessions[session_id]
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    return {"status": "ok", "message": f"Session {session_id} deleted"}

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
    """上传图片并返回 base64"""
    content = await file.read()
    b64 = base64.b64encode(content).decode("utf-8")
    return {"filename": file.filename, "base64": b64}

@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """上传音频文件，返回 Whisper 语音转录文本。"""
    try:
        content = await file.read()
        if not content:
            return {"text": "", "error": "空音频文件"}

        # 根据文件名推断后缀
        suffix = Path(file.filename).suffix if file.filename else ".webm"
        if suffix not in {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
            suffix = ".webm"

        text = await transcribe_audio(content, language="zh", suffix=suffix)
        return {"text": text, "filename": file.filename}
    except Exception as e:
        return {"text": "", "error": f"转录失败: {e}"}

@app.get("/api/transcribe/info")
def transcribe_info():
    """获取 Whisper 模型状态。"""
    return get_model_info()

# ====== 文件读取 API ======

@app.get("/api/file/read")
async def read_file_api(path: str):
    """读取文件内容，用于编辑器预览。path 为绝对路径。"""
    p, err = resolve_current_project_file(path)
    if err:
        return {"error": err}
    assert p is not None  # resolve_current_project_file returns Path when err is None

    if not p.exists():
        return {"error": f"文件不存在: {path}"}
    if not p.is_file():
        return {"error": f"路径不是文件: {path}"}

    # 安全限制：避免读取超大文件
    size = p.stat().st_size
    if size > 10 * 1024 * 1024:  # 10MB
        return {"error": f"文件过大 ({size} bytes)，拒绝读取"}

    try:
        async with aiofiles.open(p, "r", encoding="utf-8", errors="ignore") as f:
            content = await f.read()
        return {"content": content, "path": str(p)}
    except OSError as e:
        return {"error": f"文件读取错误: {e}"}


# ====== 文件保存 API ======

class WriteFileRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    content: str

@app.post("/api/file/write")
async def write_file_api(req: WriteFileRequest):
    """写入文件内容，用于编辑器保存。path 为绝对路径。"""
    p, err = resolve_current_project_file(req.path)
    if err:
        return {"error": err}
    assert p is not None
    if p.exists() and not p.is_file():
        return {"error": f"Path is not a file: {req.path}"}
    if not p.parent.exists():
        return {"error": f"父目录不存在: {p.parent}"}

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
        return {"error": f"文件写入错误: {e}"}


class RevertFileRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    old_content: str


@app.post("/api/file/revert")
async def revert_file_api(req: RevertFileRequest):
    """回退文件到指定内容（用于 Apply/Diff 审批的 Reject 操作）。"""
    p, err = resolve_current_project_file(req.path)
    if err:
        return {"error": err}
    assert p is not None
    try:
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(req.old_content)
        return {"status": "ok", "path": str(p)}
    except OSError as e:
        return {"error": {"category": "internal", "message": f"文件回退失败: {e}"}}


# ====== Plugins API ======

@app.get("/api/plugins")
def list_plugins():
    """列出所有已加载的插件。"""
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
    """重新加载所有插件。"""
    from app.plugins import get_plugin_manager
    manager = get_plugin_manager()
    manager.unload_all()
    n = manager.discover_and_load()
    return {"status": "ok", "loaded": n}


# ====== Diagnostics API ======

@app.post("/api/diagnostics/run")
async def run_diagnostics_api(source: str = ""):
    """运行项目诊断（linter/typechecker），返回结果。"""
    from app.diagnostics import run_diagnostics as run_diag, detect_linters
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "没有打开的项目"}}

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
    """获取最近一次诊断结果。"""
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
    """列出当前项目可用的 linter/typechecker。"""
    from app.diagnostics import detect_linters
    from app.project_manager import ProjectManager
    project = ProjectManager.get_current()
    if not project:
        return {"linters": []}
    return {"linters": detect_linters(project["path"])}


# ====== Test Runner API ======

@app.post("/api/tests/run")
async def run_tests_api(framework: str = "", filter: str = ""):
    """运行项目测试，返回结果。"""
    from app.test_runner import run_and_store, detect_framework
    from app.project_manager import ProjectManager

    project = ProjectManager.get_current()
    if not project:
        return {"error": {"category": "validation", "message": "没有打开的项目"}}

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
    """获取最近一次测试运行结果。"""
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
    """检测当前项目的测试框架。"""
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


@app.get("/api/skills")
def list_skills():
    """获取所有可用的 Superpowers skills"""
    return SkillManager.list_skill_catalog()


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
    """获取所有可用的 slash commands"""
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


# ====== 凭据管理 API ======

@app.get("/api/credentials")
def list_credentials():
    """获取已存储的 Git 凭据 host 列表"""
    return {"hosts": CredentialManager.list_hosts(), "gcm_available": CredentialManager.has_gcm()}

@app.post("/api/credentials")
def store_credential(req: StoreCredentialRequest):
    """存储 Git 凭据"""
    CredentialManager.store_token(req.host, req.username, req.token)
    return {"status": "stored", "host": req.host}

@app.delete("/api/credentials/{host}")
def delete_credential(host: str):
    """删除指定 host 的凭据"""
    CredentialManager.delete_token(host)
    return {"status": "deleted", "host": host}


# ====== WebSocket（核心实时通信） ======

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    if is_auth_enabled():
        token = websocket.headers.get(AUTH_HEADER) or websocket.query_params.get("token")
        if not is_valid_auth_token(token):
            await websocket.close(code=1008)
            return

    # Defense in depth: only allow local origins for WS upgrade.
    origin = websocket.headers.get("origin", "")
    if origin and not _is_local_origin(origin):
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    await websocket.accept()
    current_model = load_config().settings.default_model
    current_role_id = "desktop-agent"
    current_agent_type = "personal"

    # 发送历史会话消息（如果有）
    session = get_or_create_session(session_id, current_model)
    current_model = session.model_id  # 恢复已保存的 model
    current_role_id = session.role_id  # 恢复已保存的 role
    current_agent_type = session.agent_type  # 恢复已保存的 agent_type
    if any(m.get("role") != "system" for m in session.messages):
        await websocket.send_json({"type": "history_snapshot", "data": session.to_snapshot()})
        await websocket.send_json({
            "type": "status",
            "data": {
                "status": "history_loaded",
                "count": len([m for m in session.messages if m.get("role") != "system"]),
            },
        })

    if session.chat_mode == "plan" and session.plan_state.phase not in ("idle",):
        await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})

    await websocket.send_json({"type": "context_usage", "data": session.context_usage()})

    try:
        run_task: "asyncio.Task | None" = None

        while True:
            # 接收前端消息
            data = await websocket.receive_text()
            msg = json.loads(data)

            msg_type = msg.get("type", "chat")

            if msg_type == "chat":
                user_text = msg.get("text", "")
                model_id = msg.get("model_id", current_model)
                agent_type = _resolve_agent_type(msg.get("agent_type", current_agent_type), msg.get("role_id", current_role_id))
                role_id = msg.get("role_id") or AgentManager.get_default_role(agent_type)
                image_b64 = msg.get("image_base64")
                chat_mode = msg.get("chat_mode") or "agent"
                thinking_intensity = msg.get("thinking_intensity")
                current_model = model_id
                current_role_id = role_id
                current_agent_type = agent_type

                try:
                    session = get_or_create_session(session_id, model_id, role_id, agent_type=agent_type)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "data": validation_error(str(exc))})
                    continue

                # Cancel any in-progress run before starting a new one
                if run_task and not run_task.done():
                    session.cancel()
                    run_task.cancel()

                async def _run_agent():
                    token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                    try:
                        async for event in session.run(
                            user_text,
                            image_b64,
                            chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                            thinking_intensity=thinking_intensity
                            if thinking_intensity in ("low", "medium", "high")
                            else None,
                        ):
                            await websocket.send_json(event)
                        await websocket.send_json({"type": "done"})
                    except asyncio.CancelledError:
                        pass
                    finally:
                        reset_worker_event_callback(token)

                run_task = asyncio.create_task(_run_agent())

            elif msg_type == "clear":
                clear_session(session_id)
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await websocket.send_json({"type": "cleared"})
                await websocket.send_json({"type": "history_snapshot", "data": session.to_snapshot()})
                await websocket.send_json({"type": "context_usage", "data": session.context_usage()})

            elif msg_type == "set_chat_mode":
                mode = msg.get("chat_mode") or msg.get("chatMode") or "agent"
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if isinstance(mode, str) and session.set_session_chat_mode(mode):
                    await websocket.send_json({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})
                    if session.chat_mode == "plan" and session.plan_state.phase not in ("idle",):
                        await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})
                else:
                    await websocket.send_json({"type": "error", "data": validation_error("Invalid chat_mode")})

            elif msg_type == "set_thinking_intensity":
                intensity = msg.get("thinking_intensity") or msg.get("thinkingIntensity") or ""
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if isinstance(intensity, str) and session.set_session_thinking_intensity(intensity):
                    await websocket.send_json({
                        "type": "thinking_intensity",
                        "data": {"thinking_intensity": session.thinking_intensity},
                    })
                else:
                    await websocket.send_json({"type": "error", "data": validation_error("Invalid thinking_intensity")})

            elif msg_type == "stop":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.cancel()
                if run_task and not run_task.done():
                    run_task.cancel()
                await websocket.send_json({"type": "interrupted", "data": {"message": "已收到停止请求"}})

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
                    await websocket.send_json({"type": "error", "data": validation_error(str(exc))})
                    continue
                if session.retry_last():
                    # Cancel any in-progress run before retrying
                    if run_task and not run_task.done():
                        session.cancel()
                        run_task.cancel()

                    async def _retry_agent():
                        token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                        try:
                            async for event in session.run(
                                "",
                                None,
                                chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                                thinking_intensity=thinking_intensity
                                if thinking_intensity in ("low", "medium", "high")
                                else None,
                            ):
                                await websocket.send_json(event)
                            await websocket.send_json({"type": "done"})
                        except asyncio.CancelledError:
                            pass
                        finally:
                            reset_worker_event_callback(token)

                    run_task = asyncio.create_task(_retry_agent())
                else:
                    await websocket.send_json({"type": "error", "data": validation_error("没有可重试的消息")})

            elif msg_type == "approve_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.approve_plan()
                await websocket.send_json({"type": "plan_approved_waiting_build", "data": {}})
                await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})

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
                    await websocket.send_json({
                        "type": "model_switched",
                        "data": {"model_id": model_id, "agent_type": current_agent_type},
                    })

            elif msg_type == "reject_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                session.reject_plan()
                await websocket.send_json({"type": "plan_rejected", "data": {}})
                await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})

            elif msg_type == "compact":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                result = await session.compact_context(
                    focus=str(msg.get("focus") or ""),
                    force=bool(msg.get("force", False)),
                )
                if result:
                    await websocket.send_json({
                        "type": "compacted",
                        "data": {
                            **result,
                            "message_count": len(session.messages),
                            "source": msg.get("source") or "websocket",
                        },
                    })
                    await websocket.send_json({"type": "history_snapshot", "data": session.to_snapshot()})
                    await websocket.send_json({"type": "context_usage", "data": session.context_usage()})
                else:
                    await websocket.send_json({
                        "type": "error",
                        "data": validation_error("对话消息不足，无需压缩（至少需要 15 条消息）"),
                    })

            elif msg_type == "context":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                await websocket.send_json({"type": "context_usage", "data": session.context_usage()})

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
                    await websocket.send_json({"type": "error", "data": validation_error(str(exc))})
                    continue
                if run_task and not run_task.done():
                    session.cancel()
                    run_task.cancel()
                result = session.rewind_to_checkpoint(checkpoint_id)
                if not result:
                    await websocket.send_json({"type": "error", "data": validation_error("Checkpoint not found")})
                    continue
                await websocket.send_json({"type": "rewound", "data": result})
                await websocket.send_json({"type": "history_snapshot", "data": session.to_snapshot()})
                await websocket.send_json({"type": "context_usage", "data": session.context_usage()})
                if bool(msg.get("retry", True)):
                    async def _rewind_retry_agent():
                        token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                        try:
                            async for event in session.run(
                                "",
                                None,
                                chat_mode=chat_mode if chat_mode in ("agent", "plan") else None,
                                thinking_intensity=thinking_intensity
                                if thinking_intensity in ("low", "medium", "high")
                                else None,
                            ):
                                await websocket.send_json(event)
                            await websocket.send_json({"type": "done"})
                        except asyncio.CancelledError:
                            pass
                        finally:
                            reset_worker_event_callback(token)

                    run_task = asyncio.create_task(_rewind_retry_agent())

            elif msg_type == "build_plan":
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if not session.build_plan():
                    await websocket.send_json({"type": "error", "data": validation_error("No plan is ready to build. Wait for the plan draft first.")})
                    continue

                await websocket.send_json({"type": "build_started", "data": {}})
                await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})
                await websocket.send_json({"type": "todo_update", "data": {"todos": [t.model_dump() for t in session.plan_state.todos]}})
                # Sync frontend mode: Build auto-switches to agent mode.
                await websocket.send_json({"type": "chat_mode", "data": {"chat_mode": session.chat_mode}})

                if run_task and not run_task.done():
                    session.cancel()
                    run_task.cancel()

                async def _plan_continue_agent():
                    token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                    try:
                        async for event in session.run(PLAN_CONTINUE_MARKER, None):
                            await websocket.send_json(event)
                        await websocket.send_json({"type": "done"})
                    except asyncio.CancelledError:
                        pass
                    finally:
                        reset_worker_event_callback(token)

                run_task = asyncio.create_task(_plan_continue_agent())

            elif msg_type == "update_plan_decision":
                qid = msg.get("question_id") or msg.get("questionId")
                selected = msg.get("selected") or []
                if not isinstance(selected, list):
                    selected = [selected] if selected is not None else []
                session = get_or_create_session(session_id, current_model, current_role_id, agent_type=current_agent_type)
                if qid is not None:
                    session.update_plan_decision(str(qid), [str(s) for s in selected])
                await websocket.send_json({"type": "plan_status", "data": session.plan_event_payload()})
                if session.plan_state.phase == "awaiting_approval":
                    await websocket.send_json({
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
                    # All decisions collected — feed back to LLM for plan_write_draft.
                    if run_task and not run_task.done():
                        session.cancel()
                        run_task.cancel()

                    async def _plan_clarify_agent():
                        token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                        try:
                            async for event in session.run("", None):
                                await websocket.send_json(event)
                            await websocket.send_json({"type": "done"})
                        except asyncio.CancelledError:
                            pass
                        finally:
                            reset_worker_event_callback(token)

                    run_task = asyncio.create_task(_plan_clarify_agent())

            elif msg_type == "switch_agent":
                agent_type = msg.get("agent_type", "personal")
                if agent_type not in ("personal", "coding"):
                    await websocket.send_json({"type": "error", "data": {"message": f"Unknown agent_type: {agent_type}"}})
                    continue
                try:
                    session = get_or_create_session(session_id, current_model, role_id=current_role_id, agent_type=agent_type)
                    session.switch_agent(agent_type)
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "data": validation_error(str(exc))})
                    continue
                current_role_id = session.role_id
                current_agent_type = agent_type
                current_model = session.model_id
                await websocket.send_json({
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
                    await websocket.send_json({"type": "error", "data": validation_error(str(exc))})
                    continue
                current_role_id = role_id
                current_agent_type = agent_type
                await websocket.send_json({
                    "type": "agent_switched",
                    "data": {"agent_type": agent_type, "name": "Personal Agent" if agent_type == "personal" else "Coding Agent"},
                })

            elif msg_type == "switch_project":
                project_path = msg.get("path")
                if project_path:
                    try:
                        # open_project shells out to git up to 4× with 5s timeouts each;
                        # offloading keeps the WS event loop responsive for parallel sessions.
                        project = await asyncio.to_thread(ProjectManager.open_project, project_path)
                        await asyncio.to_thread(CredentialManager.configure_gcm, project_path)
                        await websocket.send_json({"type": "project_changed", "data": {"project": project}})
                    except ValueError as e:
                        await websocket.send_json({"type": "error", "data": validation_error(str(e))})
                else:
                    ProjectManager.close_project()
                    await websocket.send_json({"type": "project_changed", "data": {"project": None}})

            elif msg_type == "set_team":
                team_id = msg.get("team_id") or None
                team_name = msg.get("team_name", "")
                session.set_team(team_id, team_name)
                await websocket.send_json({"type": "team_set", "data": {"team_id": team_id, "team_name": team_name}})

            elif msg_type == "tool_direct":
                # 前端直接调用工具（仅限 SAFE_DIRECT_TOOLS 白名单中的只读/可见操作）
                tool_name = msg.get("tool_name")
                tool_args = msg.get("args", {})
                if tool_name not in SAFE_DIRECT_TOOLS:
                    if tool_name in list_tool_names():
                        await websocket.send_json({
                            "type": "error",
                            "data": sandbox_error(f"Tool not allowed via direct invocation: {tool_name}"),
                        })
                    else:
                        await websocket.send_json({"type": "error", "data": tool_not_found_error(tool_name)})
                    continue

                tool = get_tool(tool_name)
                try:
                    result = await tool.execute(**tool_args)
                except Exception as e:
                    failure = tool_failure_error(f"Tool execution failed: {e}", tool_name)
                    await websocket.send_json({
                        "type": "tool_result",
                        "data": {
                            "name": tool_name, "args": tool_args, "output": "",
                            "error": failure.get("message", str(e)),
                            "image": None,
                        }
                    })
                    continue
                await websocket.send_json({
                    "type": "tool_result",
                    "data": {"name": tool_name, "args": tool_args, "output": result.output, "error": result.error, "image": result.base64_image}
                })

    except WebSocketDisconnect:
        if run_task and not run_task.done():
            run_task.cancel()
        print(f"[WS] Client disconnected: {session_id}")
        # Trigger HEARTBEAT memory maintenance for Personal Agent
        try:
            import asyncio as _asyncio
            _asyncio.create_task(HeartbeatEngine.on_session_end(session.messages, session_id))
        except Exception:
            pass
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": categorize_exception(e)})
        except Exception:
            pass
