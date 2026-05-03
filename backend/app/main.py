import json
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import list_all_models, load_config, mask_api_key, save_config, reload_config
from app.config import Settings, ProviderConfig, ModelInfo
from app.agent import get_or_create_session, clear_session, SESSIONS_DIR
from app.roles import RoleManager
from app.project_manager import ProjectManager
from app.skills import SkillManager
from app.credential_manager import CredentialManager
from app.tools.worker_tool import set_worker_event_callback
from app.security import resolve_current_project_file
from app.tools import list_tool_names, get_tool
from app.transcribe import transcribe_audio, get_model_info

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

app = FastAPI(title="Desktop Agent API", lifespan=lifespan)

# CORS：允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "null"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Preview 目录静态文件服务（用于 Codex 代码预览）
from pathlib import Path
PREVIEW_DIR = Path(__file__).parent.parent / "preview"
PREVIEW_DIR.mkdir(exist_ok=True)
app.mount("/preview", StaticFiles(directory=str(PREVIEW_DIR)), name="preview")


# ====== REST API ======

class ChatRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    
    message: str
    session_id: str = "default"
    model_id: Optional[str] = None
    role_id: Optional[str] = None
    image_base64: Optional[str] = None

class OpenProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str

class CreateProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    parent_path: str
    name: str
    template: str = "empty"

class CloneProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    url: str
    path: Optional[str] = None
    token: Optional[str] = None

class StoreCredentialRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    host: str
    username: str
    token: str

# ====== Settings API models ======

class SettingsUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    default_model: Optional[str] = None
    default_provider: Optional[str] = None
    max_iterations: Optional[int] = None
    auto_approve: Optional[bool] = None
    screenshot_on_step: Optional[bool] = None

class ProviderUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    base_url: str
    api_key: str
    models: list[dict]

class NewProviderRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    base_url: str
    api_key: str
    models: list[dict] = []

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

# ====== Settings API ======

@app.get("/api/settings")
def get_settings():
    """返回所有 Provider（含脱敏 API Key）+ 全局设置"""
    cfg = load_config()
    providers = {}
    for pname, p in cfg.providers.items():
        raw_key = getattr(p, '_raw_api_key', '') or p.api_key
        providers[pname] = {
            "name": pname,
            "base_url": p.base_url,
            "api_key_masked": mask_api_key(raw_key),
            "models": [m.model_dump() for m in p.models],
        }
    return {
        "providers": providers,
        "settings": cfg.settings.model_dump(),
    }


@app.put("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    """部分更新全局设置"""
    cfg = load_config()
    update = req.model_dump(exclude_none=True)
    current = cfg.settings.model_dump()
    current.update(update)
    cfg.settings = Settings(**current)
    save_config(cfg)
    return {"status": "ok"}


@app.put("/api/providers/{provider_name}")
def update_provider(provider_name: str, req: ProviderUpdateRequest):
    """更新指定 Provider 的配置"""
    cfg = load_config()
    old_raw = getattr(cfg.providers.get(provider_name, None), '_raw_api_key', '') if provider_name in cfg.providers else ''
    # 如果请求中的 api_key 与被脱敏前的值不同，说明用户改了 key
    cfg.providers[provider_name] = ProviderConfig(
        base_url=req.base_url,
        api_key=req.api_key,
        models=[ModelInfo(**m) for m in req.models],
    )
    # 如果用户输入了新的 api_key（非空），则使用新值；否则保留旧值（支持 env var 语法）
    cfg.providers[provider_name]._raw_api_key = req.api_key if req.api_key else old_raw
    save_config(cfg)
    return {"status": "ok"}


@app.post("/api/providers")
def create_provider(req: NewProviderRequest):
    """创建新的 Provider"""
    cfg = load_config()
    if req.name in cfg.providers:
        raise HTTPException(status_code=409, detail=f"Provider '{req.name}' already exists")
    cfg.providers[req.name] = ProviderConfig(
        base_url=req.base_url,
        api_key=req.api_key,
        models=[ModelInfo(**m) for m in req.models],
    )
    cfg.providers[req.name]._raw_api_key = req.api_key
    save_config(cfg)
    return {"status": "ok"}


@app.delete("/api/providers/{provider_name}")
def delete_provider(provider_name: str):
    """删除 Provider（拒绝删除 default_provider）"""
    cfg = load_config()
    if provider_name not in cfg.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    if cfg.settings.default_provider == provider_name:
        raise HTTPException(status_code=400, detail="Cannot delete the default provider. Change the default first.")
    del cfg.providers[provider_name]
    save_config(cfg)
    return {"status": "ok"}


@app.post("/api/config/reload")
def force_config_reload():
    """强制刷新后端配置缓存"""
    cfg = reload_config()
    return {"status": "ok", "default_model": cfg.settings.default_model}


@app.get("/api/tools")
def get_tools():
    """获取所有可用工具列表"""
    from app.tools import ALL_TOOLS
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
    import json
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
    from app.agent import _sessions
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
    import base64
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

# ====== 项目管理 API ======

@app.get("/api/projects")
def list_projects():
    """获取最近项目列表和当前项目"""
    return {
        "projects": ProjectManager.list_recent(),
        "current": ProjectManager.get_current()
    }

@app.get("/api/projects/current")
def get_current_project():
    """获取当前打开的项目"""
    return ProjectManager.get_current()

@app.post("/api/projects/open")
def open_project(req: OpenProjectRequest):
    """打开一个项目目录"""
    try:
        project = ProjectManager.open_project(req.path)
        # 配置 GCM
        CredentialManager.configure_gcm(req.path)
        return project
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/projects/clone")
async def clone_project(req: CloneProjectRequest):
    """Clone a Git repository and open it as the current project."""
    from app.tools.git_tool import GitCloneTool

    try:
        if req.path:
            target = Path(req.path).resolve()
        else:
            repo_name = req.url.rstrip("/").split("/")[-1].replace(".git", "")
            current = ProjectManager.get_current()
            target = (Path(current["path"]).parent if current else Path.cwd()) / repo_name
            target = target.resolve()

        result = await GitCloneTool().execute(req.url, str(target), req.token)
        if result.error:
            return {"error": result.error}

        project = ProjectManager.open_project(str(target))
        CredentialManager.configure_gcm(str(target))
        project["message"] = result.output
        return project
    except ValueError as e:
        return {"error": str(e)}

@app.post("/api/projects/close")
def close_project():
    """关闭当前项目"""
    ProjectManager.close_project()
    return {"status": "closed"}

@app.post("/api/projects/create")
def create_project(req: CreateProjectRequest):
    """创建新项目"""
    try:
        return ProjectManager.create_project(req.parent_path, req.name, req.template)
    except ValueError as e:
        return {"error": str(e)}

@app.get("/api/projects/tree")
def get_project_tree(path: str = ""):
    """获取项目文件树"""
    return {"nodes": ProjectManager.get_tree(path)}


# ====== 文件读取 API ======

@app.get("/api/file/read")
async def read_file_api(path: str):
    """读取文件内容，用于编辑器预览。path 为绝对路径。"""
    import aiofiles
    
    p, err = resolve_current_project_file(path)
    if err:
        return {"error": err}
    
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
    import aiofiles
    
    p, err = resolve_current_project_file(req.path)
    if err:
        return {"error": err}
    if p.exists() and not p.is_file():
        return {"error": f"Path is not a file: {req.path}"}
    if not p.parent.exists():
        return {"error": f"父目录不存在: {p.parent}"}
    
    try:
        async with aiofiles.open(p, "w", encoding="utf-8") as f:
            await f.write(req.content)
        return {"status": "ok", "path": str(p)}
    except OSError as e:
        return {"error": f"文件写入错误: {e}"}


# ====== Skills API ======

@app.get("/api/skills")
def list_skills():
    """获取所有可用的 Superpowers skills"""
    return {"skills": SkillManager.list_skills()}


# ====== 知识库 API ======

class KnowledgeIndexRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    recursive: bool = True

class KnowledgeSearchRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    query: str
    top_k: int = 5
    source_filter: Optional[str] = None

@app.get("/api/knowledge/docs")
def list_knowledge_docs():
    from app.rag.engine import get_rag_engine
    return {"docs": get_rag_engine().list_docs()}

@app.post("/api/knowledge/index")
async def index_knowledge(req: KnowledgeIndexRequest):
    from app.rag.engine import get_rag_engine
    result = get_rag_engine().index_file(req.path, recursive=req.recursive)
    if "error" in result:
        return {"error": result["error"]}
    return result

@app.delete("/api/knowledge/docs")
def delete_knowledge_doc(path: str):
    from app.rag.engine import get_rag_engine
    return get_rag_engine().delete_doc(path)

@app.post("/api/knowledge/search")
async def search_knowledge(req: KnowledgeSearchRequest):
    from app.rag.engine import get_rag_engine
    results = get_rag_engine().search(req.query, top_k=req.top_k, source_filter=req.source_filter)
    return {"results": [r.model_dump() for r in results]}


# ====== 工作流 API ======

class WorkflowCreateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    description: str = ""
    steps: list = []
    variables: list = []

class WorkflowRunRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    variables: dict = {}

@app.get("/api/workflows")
def list_workflows_api():
    from app.workflow.engine import get_all_workflows
    return {"workflows": [w.model_dump() for w in get_all_workflows()]}

@app.get("/api/workflows/{workflow_id}")
def get_workflow_api(workflow_id: str):
    from app.workflow.engine import get_workflow
    wf = get_workflow(workflow_id)
    if not wf:
        return {"error": "Workflow not found"}
    return wf.model_dump()

@app.post("/api/workflows")
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

@app.delete("/api/workflows/{workflow_id}")
def delete_workflow_api(workflow_id: str):
    from app.workflow.engine import remove_workflow
    success = remove_workflow(workflow_id)
    return {"status": "deleted" if success else "not_found"}

@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow_api(workflow_id: str, req: WorkflowRunRequest):
    from app.workflow.engine import get_workflow, WorkflowExecutor
    wf = get_workflow(workflow_id)
    if not wf:
        return {"error": "Workflow not found"}
    executor = WorkflowExecutor(wf)
    events = []
    async for event in executor.run(variables=req.variables):
        events.append(event)
    return {"events": events}


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
    from app.mcp.manager import get_mcp_manager
    servers = get_mcp_manager().list_servers()
    return {"servers": [s.model_dump() for s in servers]}

@app.post("/api/mcp/servers")
def create_mcp_server(req: McpServerCreateRequest):
    import yaml
    from pathlib import Path
    mcp_path = Path("config/mcp.yaml")
    data = {}
    if mcp_path.exists():
        with open(mcp_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    if "servers" not in data:
        data["servers"] = {}
    data["servers"][req.id] = {
        "transport": req.transport,
        "command": req.command,
        "args": req.args,
        "url": req.url,
        "env": req.env,
    }
    with open(mcp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    from app.mcp.manager import get_mcp_manager
    get_mcp_manager().reload_configs()
    return {"status": "ok", "id": req.id}

@app.delete("/api/mcp/servers/{server_id}")
def delete_mcp_server(server_id: str):
    import yaml
    from pathlib import Path
    mcp_path = Path("config/mcp.yaml")
    if not mcp_path.exists():
        return {"status": "not_found"}
    with open(mcp_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "servers" in data and server_id in data["servers"]:
        del data["servers"][server_id]
        with open(mcp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    from app.mcp.manager import get_mcp_manager
    get_mcp_manager().reload_configs()
    return {"status": "deleted"}

@app.post("/api/mcp/servers/{server_id}/connect")
async def connect_mcp_server(server_id: str):
    from app.mcp.manager import get_mcp_manager
    success = await get_mcp_manager().connect(server_id)
    return {"connected": success}

@app.post("/api/mcp/servers/{server_id}/disconnect")
async def disconnect_mcp_server(server_id: str):
    from app.mcp.manager import get_mcp_manager
    await get_mcp_manager().disconnect(server_id)
    return {"status": "disconnected"}

@app.get("/api/mcp/servers/{server_id}/tools")
def list_mcp_server_tools(server_id: str):
    from app.mcp.manager import get_mcp_manager
    server = get_mcp_manager().get_server(server_id)
    if not server:
        return {"error": "Server not found"}
    return {"tools": [t.model_dump() for t in server.tools]}


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
                set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))

                async for event in session.run(user_text, image_b64):
                    await websocket.send_json(event)
                    # 小延迟避免前端渲染过载
                    await asyncio.sleep(0.01)

                set_worker_event_callback(None)
                # 发送结束标记
                await websocket.send_json({"type": "done"})
            
            elif msg_type == "clear":
                clear_session(session_id)
                await websocket.send_json({"type": "cleared"})
            
            elif msg_type == "stop":
                session = get_or_create_session(session_id, current_model)
                session.cancel()
                await websocket.send_json({"type": "interrupted", "data": {"message": "已收到停止请求"}})
            
            elif msg_type == "retry":
                model_id = msg.get("model_id", current_model)
                role_id = msg.get("role_id", "desktop-agent")
                current_model = model_id
                session = get_or_create_session(session_id, model_id, role_id)
                if session.retry_last():
                    set_worker_event_callback(lambda ev: asyncio.ensure_future(websocket.send_json(ev)))
                    async for event in session.run("", None):
                        await websocket.send_json(event)
                        await asyncio.sleep(0.01)
                    set_worker_event_callback(None)
                    await websocket.send_json({"type": "done"})
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
                        project = ProjectManager.open_project(project_path)
                        CredentialManager.configure_gcm(project_path)
                        await websocket.send_json({"type": "project_changed", "data": {"project": project}})
                    except ValueError as e:
                        await websocket.send_json({"type": "error", "data": {"message": str(e)}})
                else:
                    ProjectManager.close_project()
                    await websocket.send_json({"type": "project_changed", "data": {"project": None}})
            
            elif msg_type == "tool_direct":
                # 前端直接调用工具（用于测试或快捷操作）
                tool_name = msg.get("tool_name")
                tool_args = msg.get("args", {})
                if tool_name in list_tool_names():
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
                else:
                    await websocket.send_json({"type": "error", "data": {"message": f"Unknown tool: {tool_name}"}})
    
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {session_id}")
    except Exception as e:
        print(f"[WS] Error: {e}")
        try:
            await websocket.send_json({"type": "error", "data": {"message": str(e)}})
        except Exception:
            pass
