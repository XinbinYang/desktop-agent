"""Lightweight Worker agent for sub-task execution."""
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.models import ModelRouter
from app.message_utils import trim_messages, parse_tool_args, execute_tool

WORKER_PROFILES: Dict[str, "WorkerProfile"] = {}


@dataclass
class WorkerProfile:
    name: str
    tools: List[str] = field(default_factory=lambda: [
        "file_read", "file_write", "file_list", "file_search", "file_delete",
        "shell_execute", "shell_start",
        "browser_navigate", "browser_click", "browser_type",
        "browser_screenshot", "browser_evaluate", "browser_close",
        "git_status", "git_commit", "git_diff",
    ])
    max_iterations: int = 15
    system_prompt_extra: str = ""

    def __post_init__(self):
        WORKER_PROFILES[self.name] = self


WorkerProfile(name="code")
WorkerProfile(name="general", tools=[
    "file_read", "file_write", "file_list", "file_search", "file_delete",
    "shell_execute", "shell_start",
    "browser_navigate", "browser_click", "browser_type",
    "browser_screenshot", "browser_evaluate", "browser_close",
    "screenshot", "mouse_click", "mouse_move", "type_text", "press_key", "scroll", "get_screen_size",
    "app_open", "app_list_windows", "app_find_window", "app_click", "app_type",
    "git_clone", "git_status", "git_commit", "git_pull", "git_push", "git_branch", "git_remote",
    "wind_wsd", "wind_wss", "wind_wset", "wind_edb", "wind_tdays",
    "strategy_list", "backtest_run", "backtest_report",
    "knowledge_index", "knowledge_search", "knowledge_list",
])


class WorkerSession:
    MAX_HISTORY_MESSAGES = 20
    STALE_THRESHOLD = 3

    def __init__(self, worker_id: str, task: str, profile_name: str, model_id: str,
                 context_files: Optional[List[str]] = None):
        self.worker_id = worker_id
        self.task = task
        self.profile = WORKER_PROFILES.get(profile_name, WORKER_PROFILES["general"])
        self.model_id = model_id
        self.router = ModelRouter(model_id)
        self.messages: List[Dict[str, Any]] = []
        self.iteration = 0
        self._cancelled = False
        self._context_files = context_files or []
        self._stale_count = 0
        self._started_at = time.time()
        self._tool_schemas_cache = self._build_tool_schemas()
        self._build_system_prompt()
        self._add_task_message()

    def _build_system_prompt(self):
        from app.tools import get_static_tool, list_static_tool_names
        tool_names = self.profile.tools
        tools_desc_lines = []
        for name in tool_names:
            if name in list_static_tool_names():
                t = get_static_tool(name)
                tools_desc_lines.append(f"- {name}: {t.description}")
        tools_desc = "\n".join(tools_desc_lines)

        prompt = f"""You are a focused task execution agent. Complete the assigned task using available tools.

## Available Tools
{tools_desc}

## Rules
1. Stay focused on the assigned task. Do not do extra work.
2. Report your result clearly when done.
3. If you cannot complete the task, explain why.
4. Max {self.profile.max_iterations} steps.
"""
        if self.profile.system_prompt_extra:
            prompt += f"\n{self.profile.system_prompt_extra}\n"
        self.messages.append({"role": "system", "content": prompt})

    def _add_task_message(self):
        content = f"Task: {self.task}"
        if self._context_files:
            content += "\n\nContext files provided:\n"
            for f in self._context_files:
                content += f"- {f}\n"
        self.messages.append({"role": "user", "content": content})

    def cancel(self):
        self._cancelled = True

    async def run(self) -> AsyncGenerator[Dict[str, Any], None]:
        while self.iteration < self.profile.max_iterations:
            if self._cancelled:
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "cancelled",
                    "result": "[Worker cancelled]",
                    "iterations": self.iteration,
                    "duration_ms": round((time.time() - self._started_at) * 1000),
                }}
                return

            self.iteration += 1

            try:
                response = await self.router.chat_completion_non_stream(
                    messages=self.messages,
                    tools=self._tool_schemas_cache,
                    temperature=0.5,
                    max_tokens=4096,
                )
            except Exception as e:
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "failed",
                    "result": f"[Worker model error: {e}]",
                    "iterations": self.iteration,
                    "duration_ms": round((time.time() - self._started_at) * 1000),
                }}
                return

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            assistant_msg = {
                "role": "assistant",
                "content": message.get("content") or "",
            }
            if message.get("tool_calls"):
                assistant_msg["tool_calls"] = message["tool_calls"]
            self.messages.append(assistant_msg)

            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            if not content and not tool_calls:
                self._stale_count += 1
                if self._stale_count >= self.STALE_THRESHOLD:
                    yield {"type": "worker_done", "data": {
                        "worker_id": self.worker_id,
                        "status": "failed",
                        "result": "[Worker stalled: no output for 3 iterations]",
                        "iterations": self.iteration,
                        "duration_ms": round((time.time() - self._started_at) * 1000),
                    }}
                    return
            else:
                self._stale_count = 0

            if content:
                yield {"type": "worker_content", "data": {
                    "worker_id": self.worker_id,
                    "text": content,
                }}

            if not tool_calls:
                self._trim_messages()
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "completed",
                    "result": content,
                    "iterations": self.iteration,
                    "duration_ms": round((time.time() - self._started_at) * 1000),
                }}
                return

            tool_results = []
            from app.tools import get_static_tool
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments") or "{}"
                tool_id = tc.get("id", "")

                tool_args, parse_error = parse_tool_args(raw_args)
                if parse_error:
                    yield {"type": "worker_tool_call", "data": {
                        "worker_id": self.worker_id,
                        "name": tool_name,
                        "args": {},
                        "result": parse_error,
                        "duration_ms": 0,
                    }}
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": parse_error,
                    })
                    continue

                tc_result = await execute_tool(
                    tool_name, tool_args, self.profile.tools, self.worker_id,
                    get_tool_fn=get_static_tool,
                )

                yield {"type": "worker_tool_call", "data": {
                    "worker_id": self.worker_id,
                    "name": tool_name,
                    "args": tool_args,
                    "result": tc_result.result_text,
                    "duration_ms": tc_result.duration_ms,
                }}

                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": tc_result.result_text,
                })

            self.messages.extend(tool_results)
            self._trim_messages()

        yield {"type": "worker_done", "data": {
            "worker_id": self.worker_id,
            "status": "max_iterations_reached",
            "result": f"[Worker stopped: max {self.profile.max_iterations} iterations]",
            "iterations": self.iteration,
            "duration_ms": round((time.time() - self._started_at) * 1000),
        }}

    def _trim_messages(self):
        self.messages = trim_messages(self.messages, self.MAX_HISTORY_MESSAGES)

    def _build_tool_schemas(self) -> List[Dict[str, Any]]:
        from app.tools import get_static_tool, list_static_tool_names
        schemas = []
        for name in self.profile.tools:
            if name in list_static_tool_names():
                schemas.append(get_static_tool(name).get_openai_schema())
        return schemas
