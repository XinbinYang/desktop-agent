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
from pydantic import BaseModel

from app.agent import SESSIONS_DIR, _sessions, clear_session, get_or_create_session, refresh_all_sessions_mcp_tools
from app.config import list_all_models, load_config
from app.credential_manager import CredentialManager
from app.mcp.manager import MCP_CONFIG_PATH, get_mcp_manager
from app.project_manager import ProjectManager
from app.roles import RoleManager
from app.runtime_paths import runtime_dir
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
    yield
    print("[Desktop Agent] Backend shutting down...")
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


@app.middleware("http")
async def local_auth_middleware(request: Request, call_next):
    """Protect local HTTP APIs when DESKTOP_AGENT_AUTH_TOKEN is configured."""
    if request.method == "OPTIONS":
        return await call_next(request)

    if is_auth_enabled() and request.url.path.startswith("/api/"):
        token = request.headers.get(AUTH_HEADER) or request.query_params.get("token")
        if not is_valid_auth_token(token):
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized local Desktop Agent API request"},
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

app.include_router(settings_router)
app.include_router(projects_router)
app.include_router(knowledge_router)
app.include_router(workflows_router)


# ====== REST API ======

class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    message: str
    session_id: str = "default"
    model_id: Optional[str] = None
    role_id: Optional[str] = None
    image_base64: Optional[str] = None

class StoreCredentialRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    host: str
    username: str
    token: str

@app.get("/api/models")
def get_models():
    """获取所有可用模型列表"""
    return {"models": list_all_models(), "default": load_config().settings.default_model}

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
    role_id = req.role_id or "desktop-agent"
    session = get_or_create_session(req.session_id, model_id, role_id)

    results = []
    async for event in session.run(req.message, req.image_base64):
        results.append(event)

    return {"events": results}

@app.get("/api/sessions")
def list_sessions():
    """获取所有保存的会话列表"""
    sessions = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append({
                "id": data.get("session_id", path.stem),
                "model_id": data.get("model_id", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            pass
    return {"sessions": sorted(sessions, key=lambda s: s["id"])}

@app.post("/api/sessions/{session_id}/clear")
def clear_chat(session_id: str):
    clear_session(session_id)
    return {"status": "ok", "message": f"Session {session_id} cleared"}

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


# ====== Skills API ======

@app.get("/api/skills")
def list_skills():
    """获取所有可用的 Superpowers skills"""
    return {"skills": SkillManager.list_skills()}


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
        token = websocket.query_params.get("token")
        if not is_valid_auth_token(token):
            await websocket.close(code=1008)
            return

    await websocket.accept()
    current_model = load_config().settings.default_model

    # 发送历史会话消息（如果有）
    session = get_or_create_session(session_id, current_model)
    current_model = session.model_id  # 恢复已保存的 model
    history_events = session.get_history_events()
    if history_events:
        for event in history_events:
            await websocket.send_json(event)
        await websocket.send_json({"type": "status", "data": {"status": "history_loaded", "count": len(history_events)}})

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
                role_id = msg.get("role_id", "desktop-agent")
                image_b64 = msg.get("image_base64")
                current_model = model_id

                session = get_or_create_session(session_id, model_id, role_id)

                # Cancel any in-progress run before starting a new one
                if run_task and not run_task.done():
                    session.cancel()
                    run_task.cancel()

                async def _run_agent():
                    token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                    try:
                        async for event in session.run(user_text, image_b64):
                            await websocket.send_json(event)
                        await websocket.send_json({"type": "done"})
                    except asyncio.CancelledError:
                        pass
                    finally:
                        reset_worker_event_callback(token)

                run_task = asyncio.create_task(_run_agent())

            elif msg_type == "clear":
                clear_session(session_id)
                await websocket.send_json({"type": "cleared"})

            elif msg_type == "stop":
                session = get_or_create_session(session_id, current_model)
                session.cancel()
                if run_task and not run_task.done():
                    run_task.cancel()
                await websocket.send_json({"type": "interrupted", "data": {"message": "已收到停止请求"}})

            elif msg_type == "retry":
                model_id = msg.get("model_id", current_model)
                role_id = msg.get("role_id", "desktop-agent")
                current_model = model_id
                session = get_or_create_session(session_id, model_id, role_id)
                if session.retry_last():
                    # Cancel any in-progress run before retrying
                    if run_task and not run_task.done():
                        session.cancel()
                        run_task.cancel()

                    async def _retry_agent():
                        token = set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                        try:
                            async for event in session.run("", None):
                                await websocket.send_json(event)
                            await websocket.send_json({"type": "done"})
                        except asyncio.CancelledError:
                            pass
                        finally:
                            reset_worker_event_callback(token)

                    run_task = asyncio.create_task(_retry_agent())
                else:
                    await websocket.send_json({"type": "error", "data": {"message": "没有可重试的消息"}})

            elif msg_type == "switch_role":
                role_id = msg.get("role_id", "desktop-agent")
                session = get_or_create_session(session_id, current_model, role_id)
                session.switch_role(role_id)
                await websocket.send_json({"type": "status", "data": {"status": "role_switched", "role_id": role_id}})

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
                        await websocket.send_json({"type": "error", "data": {"message": str(e)}})
                else:
                    ProjectManager.close_project()
                    await websocket.send_json({"type": "project_changed", "data": {"project": None}})

            elif msg_type == "tool_direct":
                # 前端直接调用工具（仅限 SAFE_DIRECT_TOOLS 白名单中的只读/可见操作）
                tool_name = msg.get("tool_name")
                tool_args = msg.get("args", {})
                if tool_name not in SAFE_DIRECT_TOOLS:
                    if tool_name in list_tool_names():
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": f"Tool not allowed via direct invocation: {tool_name}"},
                        })
                    else:
                        await websocket.send_json({"type": "error", "data": {"message": f"Unknown tool: {tool_name}"}})
                    continue

                tool = get_tool(tool_name)
                try:
                    result = await tool.execute(**tool_args)
                except Exception as e:
                    await websocket.send_json({
                        "type": "tool_result",
                        "data": {"name": tool_name, "args": tool_args, "output": "", "error": f"Tool execution failed: {e}", "image": None}
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
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        except Exception:
            pass
