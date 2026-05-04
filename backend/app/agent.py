import json
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.config import load_config
from app.models import ModelRouter
from app.project_manager import ProjectManager
from app.roles import RoleManager
from app.skills import SkillManager
from app.tools import get_tool, get_tool_schemas, list_tool_names, DynamicToolRegistry
from app.tools.browser_tool import set_browser_session
from app.tools.desktop_tool import ScreenshotTool
from app.tools.workflow_tool import get_recorder
from app.message_utils import trim_messages, parse_tool_args, execute_tool

SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


class AgentSession:
    MAX_HISTORY_MESSAGES = 20

    def __init__(self, model_id: str, session_id: str = "default", role_id: str = "desktop-agent"):
        self.session_id = session_id
        self.model_id = model_id
        self.role_id = role_id
        self.router = ModelRouter(model_id)
        self.messages: List[Dict[str, Any]] = []
        self.iteration = 0
        self.max_iterations = load_config().settings.max_iterations
        self.screenshot_on_step = load_config().settings.screenshot_on_step
        self._cancelled = False
        self._active_workers: List[Any] = []
        self._last_user_message = ""
        self.dynamic_registry = DynamicToolRegistry()
        self._setup_system_prompt()

    def _build_system_prompt(self) -> str:
        all_schemas = get_tool_schemas(self.dynamic_registry)
        tools_desc = "\n".join([
            f"- {t['function']['name']}: {t['function']['description']}"
            for t in all_schemas
        ])
        system_msg = RoleManager.render_prompt(self.role_id, tools_desc)

        project = ProjectManager.get_current()
        if project:
            project_ctx = "\n\n## Current Project\n"
            project_ctx += f"- Name: {project['name']}\n"
            project_ctx += f"- Path: {project['path']}\n"
            if project.get("git_branch"):
                project_ctx += f"- Git branch: {project['git_branch']}\n"
            if project.get("git_remote"):
                project_ctx += f"- Git remote: {project['git_remote']}\n"
            system_msg += project_ctx

        if self._last_user_message:
            matched_skills = SkillManager.match_skills(
                self._last_user_message, self.role_id, project is not None
            )
            if matched_skills:
                skill_prompt = SkillManager.build_skill_prompt(matched_skills)
                if skill_prompt:
                    system_msg += f"\n\n## Active Skills\n{skill_prompt}\n"

        return system_msg

    def _setup_system_prompt(self):
        self.messages.append({"role": "system", "content": self._build_system_prompt()})

    def _refresh_system_prompt(self):
        system_msg = {"role": "system", "content": self._build_system_prompt()}
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = system_msg
        else:
            self.messages.insert(0, system_msg)

    def _event(self, event_type: str, data: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> Dict[str, Any]:
        event_data = dict(data or {})
        if run_id:
            event_data.setdefault("run_id", run_id)
        event_data.setdefault("iteration", self.iteration)
        event_data.setdefault("timestamp", time.time())
        return {"type": event_type, "data": event_data}

    def _trim_messages(self):
        """Trim history without splitting assistant tool_calls from their tool results."""
        self.messages = trim_messages(
            self.messages,
            self.MAX_HISTORY_MESSAGES,
            build_system_prompt_fn=self._build_system_prompt,
            validate_tool_ids=True,
        )

    async def run(
        self,
        user_input: str,
        image_base64: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Run one agent turn. Empty user_input means retry mode."""
        self.iteration = 0
        self._cancelled = False
        run_id = f"{self.session_id}-{uuid.uuid4().hex[:12]}"

        if user_input:
            self._last_user_message = user_input
            self._refresh_system_prompt()
            if image_base64:
                user_msg = self.router.build_vision_message(user_input, image_base64)
            else:
                user_msg = {"role": "user", "content": user_input}
            self.messages.append(user_msg)
            self._trim_messages()

        active_skills: List[str] = []
        if self._last_user_message:
            project = ProjectManager.get_current()
            active_skills = SkillManager.match_skills(
                self._last_user_message, self.role_id, project is not None
            )

        yield self._event("status", {"status": "thinking"}, run_id)

        finished = False
        while self.iteration < self.max_iterations:
            if self._cancelled:
                yield self._event("interrupted", {"message": "User cancelled"}, run_id)
                finished = True
                break

            self.iteration += 1

            if self.screenshot_on_step and self._should_screenshot():
                ss_tool = ScreenshotTool()
                ss_result = await ss_tool.execute()
                if ss_result.base64_image:
                    ss_content = [
                        {"type": "text", "text": "[System screenshot - current screen state]"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{ss_result.base64_image}"}}
                    ]
                    if self.messages and self.messages[-1].get("role") == "user":
                        last_content = self.messages[-1].get("content", [])
                        if isinstance(last_content, list):
                            last_content.extend(ss_content)
                        else:
                            self.messages[-1]["content"] = [{"type": "text", "text": str(last_content)}] + ss_content
                    else:
                        self.messages.append({
                            "role": "user",
                            "content": ss_content
                        })

            try:
                response = await self.router.chat_completion_non_stream(
                    messages=self.messages,
                    tools=get_tool_schemas(self.dynamic_registry),
                    temperature=0.5,
                    max_tokens=4096
                )
            except Exception as e:
                error_msg = str(e)
                if "does not support tools" in error_msg or "tool" in error_msg.lower() or "tools" in error_msg.lower():
                    try:
                        response = await self.router.chat_completion_non_stream(
                            messages=self.messages,
                            temperature=0.5,
                            max_tokens=4096
                        )
                    except Exception as e2:
                        yield self._event("error", {"message": f"Model call failed: {e2}"}, run_id)
                        finished = True
                        break
                else:
                    yield self._event("error", {"message": f"Model call failed: {e}"}, run_id)
                    finished = True
                    break

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            assistant_msg = {
                "role": "assistant",
                "content": message.get("content") or ""
            }
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            if message.get("reasoning_content"):
                assistant_msg["reasoning_content"] = message["reasoning_content"]
            self.messages.append(assistant_msg)

            reasoning = message.get("reasoning_content")
            if reasoning:
                chunk_size = max(1, len(reasoning) // 20)
                for i in range(0, len(reasoning), chunk_size):
                    yield self._event(
                        "reasoning",
                        {"text": reasoning[i:i + chunk_size], "skill": active_skills[0] if active_skills else None},
                        run_id,
                    )

            if message.get("content"):
                yield self._event(
                    "content",
                    {"text": message["content"], "skill": active_skills[0] if active_skills else None},
                    run_id,
                )

            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                self._trim_messages()
                self._save()
                yield self._event("status", {"status": "completed"}, run_id)
                finished = True
                break

            tool_results = []
            allowed_names = list_tool_names(self.dynamic_registry)
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments") or "{}"
                tool_id = tc.get("id", "")

                tool_args, parse_error = parse_tool_args(raw_args)
                if parse_error:
                    yield self._event(
                        "tool_call",
                        {"name": tool_name, "args": {}, "result": parse_error, "tool_call_id": tool_id},
                        run_id,
                    )
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": parse_error,
                    })
                    continue

                yield self._event("status", {"status": "executing", "tool": tool_name, "tool_call_id": tool_id}, run_id)

                set_browser_session(self.session_id)
                tc_result = await execute_tool(
                    tool_name, tool_args, allowed_names, self.session_id,
                    get_tool_fn=lambda name: get_tool(name, self.dynamic_registry),
                )

                if tc_result.base64_image:
                    yield self._event("image", {"base64": tc_result.base64_image, "source": tool_name, "tool_call_id": tool_id}, run_id)

                # 录制工作流步骤
                recorder = get_recorder(self.session_id)
                if recorder and recorder.is_recording() and not tc_result.error:
                    recorder.record_step(tool_name, tool_args)

                yield self._event(
                    "tool_call",
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "result": tc_result.result_text,
                        "tool_call_id": tool_id,
                        "duration_ms": tc_result.duration_ms,
                    },
                    run_id,
                )

                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result_text
                })

            self.messages.extend(tool_results)
            self._trim_messages()
            self._save()
            yield self._event("status", {"status": "thinking"}, run_id)

        if not finished and self.iteration >= self.max_iterations:
            yield self._event("status", {"status": "max_iterations_reached"}, run_id)
        self._save()

    def _should_screenshot(self) -> bool:
        desktop_tools = ["mouse_click", "mouse_move", "type_text", "press_key", "scroll", "app_click"]
        if self.messages:
            last = self.messages[-1]
            if last.get("role") == "assistant" and "tool_calls" in last:
                for tc in last["tool_calls"]:
                    if tc.get("function", {}).get("name") in desktop_tools:
                        return True
        return self.iteration % 5 == 0

    def cancel(self):
        self._cancelled = True
        for worker in self._active_workers:
            try:
                worker.cancel()
            except Exception:
                pass

    def retry_last(self) -> bool:
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if msg.get("role") == "assistant":
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

    def switch_role(self, role_id: str):
        self.role_id = role_id
        self._refresh_system_prompt()
        self._save()

    def refresh_mcp_tools(self):
        """从 MCP Manager 刷新动态工具到当前会话。"""
        from app.mcp.manager import get_mcp_manager
        from app.tools.mcp_tool import McpToolProxy
        manager = get_mcp_manager()
        self.dynamic_registry.clear()
        for server_status in manager.list_servers():
            if server_status.connected:
                for t in server_status.tools:
                    proxy = McpToolProxy(
                        server_id=server_status.id,
                        tool_name=t.name,
                        description=t.description,
                        parameters=t.parameters,
                    )
                    self.dynamic_registry.register(proxy)
        self._refresh_system_prompt()
        self._save()

    def _save(self):
        path = SESSIONS_DIR / f"{self.session_id}.json"
        data = {
            "session_id": self.session_id,
            "model_id": self.model_id,
            "role_id": self.role_id,
            "messages": self.messages,
            "iteration": self.iteration,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    @classmethod
    def load(cls, session_id: str) -> Optional["AgentSession"]:
        path = SESSIONS_DIR / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = cls(
                model_id=data.get("model_id", "kimi-for-coding"),
                session_id=session_id,
                role_id=data.get("role_id", "desktop-agent"),
            )
            session.messages = data.get("messages", [])
            session.iteration = 0
            session._trim_messages()
            session._refresh_system_prompt()
            return session
        except (OSError, json.JSONDecodeError):
            return None

    def get_history_events(self) -> List[Dict[str, Any]]:
        events = []
        for msg in self.messages:
            role = msg.get("role")
            if role == "user":
                continue
            if role == "assistant":
                if msg.get("reasoning_content"):
                    events.append({"type": "reasoning", "data": {"text": msg["reasoning_content"]}})
                if msg.get("content"):
                    events.append({"type": "content", "data": {"text": msg["content"]}})
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except (TypeError, ValueError, json.JSONDecodeError):
                            args = {}
                        events.append({
                            "type": "tool_call",
                            "data": {
                                "name": func.get("name", ""),
                                "args": args,
                                "result": "[executed]",
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


_sessions: Dict[str, AgentSession] = {}


def get_or_create_session(session_id: str, model_id: str, role_id: str = "desktop-agent") -> AgentSession:
    if session_id not in _sessions:
        loaded = AgentSession.load(session_id)
        if loaded and loaded.model_id == model_id:
            _sessions[session_id] = loaded
        else:
            _sessions[session_id] = AgentSession(model_id=model_id, session_id=session_id, role_id=role_id)
    else:
        if _sessions[session_id].model_id != model_id:
            _sessions[session_id] = AgentSession(model_id=model_id, session_id=session_id, role_id=role_id)
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
