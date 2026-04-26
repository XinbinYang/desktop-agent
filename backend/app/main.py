import json
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import list_all_models, load_config
from app.agent import get_or_create_session, clear_session, SESSIONS_DIR
from app.tools import list_tool_names, get_tool

# 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时检查
    print("[Desktop Agent] Backend starting...")
    print(f"[Desktop Agent] Available tools: {list_tool_names()}")
    yield
    print("[Desktop Agent] Backend shutting down...")

app = FastAPI(title="Desktop Agent API", lifespan=lifespan)

# CORS：允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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
    image_base64: Optional[str] = None

@app.get("/api/models")
def get_models():
    """获取所有可用模型列表"""
    return {"models": list_all_models(), "default": load_config().settings.default_model}

@app.get("/api/tools")
def get_tools():
    """获取所有可用工具列表"""
    from app.tools import ALL_TOOLS
    return {"tools": [{"name": t.name, "description": t.description} for t in ALL_TOOLS]}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    """非流式聊天（测试用）"""
    model_id = req.model_id or load_config().settings.default_model
    session = get_or_create_session(req.session_id, model_id)
    
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

# ====== WebSocket（核心实时通信） ======

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    current_model = load_config().settings.default_model
    
    # 发送历史会话消息（如果有）
    session = get_or_create_session(session_id, current_model)
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
                image_b64 = msg.get("image_base64")
                current_model = model_id
                
                session = get_or_create_session(session_id, model_id)
                
                async for event in session.run(user_text, image_b64):
                    await websocket.send_json(event)
                    # 小延迟避免前端渲染过载
                    await asyncio.sleep(0.01)
                
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
                current_model = model_id
                session = get_or_create_session(session_id, model_id)
                if session.retry_last():
                    async for event in session.run("", None):
                        await websocket.send_json(event)
                        await asyncio.sleep(0.01)
                    await websocket.send_json({"type": "done"})
                else:
                    await websocket.send_json({"type": "error", "data": {"message": "没有可重试的消息"}})
            
            elif msg_type == "tool_direct":
                # 前端直接调用工具（用于测试或快捷操作）
                tool_name = msg.get("tool_name")
                tool_args = msg.get("args", {})
                if tool_name in list_tool_names():
                    tool = get_tool(tool_name)
                    result = await tool.execute(**tool_args)
                    await websocket.send_json({
                        "type": "tool_result",
                        "data": {"name": tool_name, "output": result.output, "error": result.error, "image": result.base64_image}
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