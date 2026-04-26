import json
import base64
import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Any
from app.config import load_config
from app.models import ModelRouter
from app.tools import get_tool_schemas, get_tool, list_tool_names
from app.tools.desktop_tool import ScreenshotTool
from app.tools.browser_tool import set_browser_session

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

class AgentSession:
    MAX_HISTORY_MESSAGES = 20  # 保留最近 20 条对话消息（不含 system prompt）

    def __init__(self, model_id: str, session_id: str = "default"):
        self.session_id = session_id
        self.model_id = model_id
        self.router = ModelRouter(model_id)
        self.messages: List[Dict[str, Any]] = []
        self.iteration = 0
        self.max_iterations = load_config().settings.max_iterations
        self.screenshot_on_step = load_config().settings.screenshot_on_step
        self._cancelled = False
        self._setup_system_prompt()

    def _trim_messages(self):
        """截断消息历史，保留 system prompt + 最近 N 条消息"""
        if len(self.messages) <= self.MAX_HISTORY_MESSAGES + 1:
            return
        # 第一条是 system prompt，保留
        system_msg = self.messages[0]
        # 保留最近 N 条
        recent = self.messages[-self.MAX_HISTORY_MESSAGES:]
        self.messages = [system_msg] + recent
    
    def _setup_system_prompt(self):
        cfg = load_config()
        tools_desc = "\n".join([
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in get_tool_schemas()
        ])
        
        system_msg = (
            "你是一个桌面个人 Agent，可以帮助用户操控电脑、执行任务。"
            "你支持文件操作、终端命令、浏览器控制、桌面键鼠操作和应用程序控制。"
            f"\n\n当前可用工具:\n{tools_desc}\n\n"
            "规则:\n"
            "1. 每次响应请选择调用工具或直接回答。\n"
            "2. 执行多步骤任务时，逐步思考（Think step by step）。\n"
            "3. 操作文件前建议先查看确认。\n"
            "4. 桌面操作时，如果需要视觉反馈，请调用 screenshot 工具查看屏幕。\n"
            "5. 遇到错误时尝试修正或向用户说明。\n"
            "6. 如果任务完成，请明确告知用户结果。\n"
            "7. 当用户要求写网页、可视化、动画或小游戏时，使用 file_write 工具将代码写入 preview/ 目录（如 preview/index.html），写入后告知用户可在右侧预览面板查看效果。\n"
            "8. 当用户要求写 Python 脚本时，使用 file_write 写入 preview/script.py，然后使用 shell_execute 运行并展示输出结果。"
        )
        self.messages.append({"role": "system", "content": system_msg})
    
    async def run(
        self, 
        user_input: str,
        image_base64: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """运行 Agent 循环，产生事件流供前端消费。
        
        user_input 为空字符串时表示重试模式（不添加新的 user 消息）。
        """
        
        # 构建用户消息（仅在非重试模式下）
        if user_input:
            if image_base64:
                user_msg = self.router.build_vision_message(user_input, image_base64)
            else:
                user_msg = {"role": "user", "content": user_input}
            self.messages.append(user_msg)
            self._trim_messages()
        
        yield {"type": "status", "data": {"status": "thinking", "iteration": self.iteration}}
        
        while self.iteration < self.max_iterations:
            if self._cancelled:
                yield {"type": "interrupted", "data": {"message": "用户已取消"}}
                break
            self.iteration += 1
            
            # 可选：每步截图供模型观察（如果开启）
            if self.screenshot_on_step and self._should_screenshot():
                ss_tool = ScreenshotTool()
                ss_result = await ss_tool.execute()
                if ss_result.base64_image:
                    # 将截图作为上下文注入（ Anthropic 的 computer-use 风格）
                    self.messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "[系统截图 - 当前屏幕状态]"},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ss_result.base64_image}"}}
                        ]
                    })
            
            try:
                response = await self.router.chat_completion_non_stream(
                    messages=self.messages,
                    tools=get_tool_schemas(),
                    temperature=0.5,
                    max_tokens=4096
                )
            except Exception as e:
                error_msg = str(e)
                # 模型不支持 tools 时降级为纯文本对话
                if "does not support tools" in error_msg or "tool" in error_msg.lower() or "tools" in error_msg.lower():
                    try:
                        response = await self.router.chat_completion_non_stream(
                            messages=self.messages,
                            temperature=0.5,
                            max_tokens=4096
                        )
                    except Exception as e2:
                        yield {"type": "error", "data": {"message": f"模型调用失败: {e2}"}}
                        break
                elif isinstance(e, (ConnectionError, TimeoutError)):
                    yield {"type": "error", "data": {"message": f"模型调用失败: {e}"}}
                    break
                else:
                    yield {"type": "error", "data": {"message": f"模型调用失败: {e}"}}
                    break
            
            # 解析响应
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            
            # 将助手消息加入历史
            assistant_msg = {
                "role": "assistant",
                "content": message.get("content") or ""
            }
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            # Kimi K2.6 等 reasoning 模型需要保留 reasoning_content
            if message.get("reasoning_content"):
                assistant_msg["reasoning_content"] = message["reasoning_content"]
            self.messages.append(assistant_msg)
            self._save()
            
            # 流式输出思考过程（模拟打字机效果）
            reasoning = message.get("reasoning_content")
            if reasoning:
                chunk_size = max(1, len(reasoning) // 20)
                for i in range(0, len(reasoning), chunk_size):
                    yield {"type": "reasoning", "data": {"text": reasoning[i:i+chunk_size]}}
            
            # 流式输出正式回复内容
            if message.get("content"):
                yield {"type": "content", "data": {"text": message["content"]}}
            
            # 处理工具调用
            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                # 没有工具调用，任务结束
                yield {"type": "status", "data": {"status": "completed", "iteration": self.iteration}}
                break
            
            # 执行工具
            tool_results = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                tool_args = json.loads(func.get("arguments", "{}"))
                tool_id = tc.get("id", "")
                
                if tool_name not in list_tool_names():
                    result_text = f"[ERROR] 未知工具: {tool_name}"
                    yield {"type": "tool_call", "data": {"name": tool_name, "args": tool_args, "result": result_text}}
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": result_text
                    })
                    continue
                
                yield {"type": "status", "data": {"status": "executing", "tool": tool_name}}
                
                tool = get_tool(tool_name)
                set_browser_session(self.session_id)
                try:
                    result = await tool.execute(**tool_args)
                    result_text = result.to_text()
                    
                    # 如果有截图，额外发送给前端展示
                    if result.base64_image:
                        yield {"type": "image", "data": {"base64": result.base64_image, "source": tool_name}}
                    
                    yield {"type": "tool_call", "data": {"name": tool_name, "args": tool_args, "result": result_text}}
                except (OSError, ValueError, RuntimeError) as e:
                    result_text = f"[ERROR] 工具执行异常: {e}"
                    yield {"type": "tool_call", "data": {"name": tool_name, "args": tool_args, "result": result_text}}
                
                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result_text
                })
            
            # 将工具结果加入消息历史
            self.messages.extend(tool_results)
            self._save()
            yield {"type": "status", "data": {"status": "thinking", "iteration": self.iteration}}
        
        if self.iteration >= self.max_iterations:
            yield {"type": "status", "data": {"status": "max_iterations_reached", "iteration": self.iteration}}
        self._save()
    
    def _should_screenshot(self) -> bool:
        """判断当前步骤是否需要自动截图（简化逻辑：每5步或涉及桌面操作时）"""
        desktop_tools = ["mouse_click", "mouse_move", "type_text", "press_key", "scroll", "app_click"]
        if self.messages:
            last = self.messages[-1]
            if last.get("role") == "assistant" and "tool_calls" in last:
                for tc in last["tool_calls"]:
                    if tc.get("function", {}).get("name") in desktop_tools:
                        return True
        return self.iteration % 5 == 0
    
    def cancel(self):
        """请求取消当前正在运行的 Agent 循环。"""
        self._cancelled = True

    def retry_last(self) -> bool:
        """删除最后一条 assistant 消息及其后的 tool results，为重试做准备。
        返回是否成功找到并删除了 assistant 消息。"""
        # 从末尾向前找，找到最后一条 assistant 消息的位置
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.get("role") == "assistant":
                # 删除这条 assistant 及之后的所有消息
                self.messages = self.messages[:i]
                self.iteration = 0
                self._cancelled = False
                return True
        return False

    def reset(self):
        self.messages = []
        self.iteration = 0
        self._cancelled = False
        self._setup_system_prompt()
        self._save()

    def _save(self):
        """将会话保存到本地 JSON 文件。"""
        path = SESSIONS_DIR / f"{self.session_id}.json"
        data = {
            "session_id": self.session_id,
            "model_id": self.model_id,
            "messages": self.messages,
            "iteration": self.iteration,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # 保存失败不影响正常运行

    @classmethod
    def load(cls, session_id: str) -> Optional["AgentSession"]:
        """从本地 JSON 文件加载会话。"""
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = cls(model_id=data.get("model_id", "kimi-for-coding"), session_id=session_id)
            session.messages = data.get("messages", [])
            session.iteration = data.get("iteration", 0)
            return session
        except (OSError, json.JSONDecodeError):
            return None

    def get_history_events(self) -> List[Dict[str, Any]]:
        """将会话历史转换为前端可渲染的事件列表。"""
        events = []
        for msg in self.messages:
            role = msg.get("role")
            if role == "user":
                # user 消息不通过事件发送（前端已有）
                continue
            elif role == "assistant":
                if msg.get("reasoning_content"):
                    events.append({"type": "reasoning", "data": {"text": msg["reasoning_content"]}})
                if msg.get("content"):
                    events.append({"type": "content", "data": {"text": msg["content"]}})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        events.append({
                            "type": "tool_call",
                            "data": {
                                "name": func.get("name", ""),
                                "args": json.loads(func.get("arguments", "{}")),
                                "result": "[已执行]",
                            }
                        })
            elif role == "tool":
                events.append({
                    "type": "tool_call",
                    "data": {
                        "name": msg.get("name", ""),
                        "args": {},
                        "result": msg.get("content", ""),
                    }
                })
        return events

# 全局会话管理
_sessions: Dict[str, AgentSession] = {}

def get_or_create_session(session_id: str, model_id: str) -> AgentSession:
    if session_id not in _sessions:
        loaded = AgentSession.load(session_id)
        if loaded and loaded.model_id == model_id:
            _sessions[session_id] = loaded
        else:
            _sessions[session_id] = AgentSession(model_id=model_id, session_id=session_id)
    else:
        if _sessions[session_id].model_id != model_id:
            _sessions[session_id] = AgentSession(model_id=model_id, session_id=session_id)
    return _sessions[session_id]

def clear_session(session_id: str):
    if session_id in _sessions:
        _sessions[session_id].reset()
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass