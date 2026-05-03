"""Lightweight Worker agent for sub-task execution."""
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.models import ModelRouter
from app.tools import get_static_tool, list_static_tool_names

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
        self._build_system_prompt()
        self._add_task_message()

    def _build_system_prompt(self):
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
                    "duration_ms": 0,
                }}
                return

            self.iteration += 1

            try:
                response = await self.router.chat_completion_non_stream(
                    messages=self.messages,
                    tools=self._get_worker_tool_schemas(),
                    temperature=0.5,
                    max_tokens=4096,
                )
            except Exception as e:
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "failed",
                    "result": f"[Worker model error: {e}]",
                    "iterations": self.iteration,
                    "duration_ms": 0,
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
                        "duration_ms": 0,
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
                    "duration_ms": 0,
                }}
                return

            tool_results = []
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                raw_args = func.get("arguments") or "{}"
                tool_id = tc.get("id", "")

                try:
                    tool_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if not isinstance(tool_args, dict):
                        raise ValueError("tool arguments must be a JSON object")
                except (TypeError, ValueError, json.JSONDecodeError) as e:
                    result_text = f"[ERROR] Tool argument parse failed: {e}"
                    yield {"type": "worker_tool_call", "data": {
                        "worker_id": self.worker_id,
                        "name": tool_name,
                        "args": {},
                        "result": result_text,
                    }}
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": result_text,
                    })
                    continue

                if tool_name not in self.profile.tools:
                    result_text = f"[ERROR] Tool not available to worker: {tool_name}"
                    yield {"type": "worker_tool_call", "data": {
                        "worker_id": self.worker_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": result_text,
                    }}
                    tool_results.append({
                        "tool_call_id": tool_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": result_text,
                    })
                    continue

                try:
                    tool = get_static_tool(tool_name)
                    started_at = time.time()
                    result = await tool.execute(**tool_args)
                    result_text = result.to_text()
                    duration_ms = round((time.time() - started_at) * 1000)

                    yield {"type": "worker_tool_call", "data": {
                        "worker_id": self.worker_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": result_text,
                        "duration_ms": duration_ms,
                    }}
                except Exception as e:
                    result_text = f"[ERROR] Tool execution failed: {e}"
                    yield {"type": "worker_tool_call", "data": {
                        "worker_id": self.worker_id,
                        "name": tool_name,
                        "args": tool_args,
                        "result": result_text,
                    }}

                tool_results.append({
                    "tool_call_id": tool_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": result_text,
                })

            self.messages.extend(tool_results)
            self._trim_messages()

        yield {"type": "worker_done", "data": {
            "worker_id": self.worker_id,
            "status": "max_iterations_reached",
            "result": f"[Worker stopped: max {self.profile.max_iterations} iterations]",
            "iterations": self.iteration,
            "duration_ms": 0,
        }}

    def _trim_messages(self):
        system_msg = self.messages[0] if self.messages and self.messages[0].get("role") == "system" else {"role": "system", "content": ""}
        body = self.messages[1:] if self.messages and self.messages[0].get("role") == "system" else self.messages
        groups = []
        i = 0
        while i < len(body):
            msg = body[i]
            role = msg.get("role")
            if role == "tool":
                i += 1
                continue
            if role == "assistant" and msg.get("tool_calls"):
                group = [msg]
                i += 1
                while i < len(body) and body[i].get("role") == "tool":
                    group.append(body[i])
                    i += 1
                groups.append(group)
                continue
            groups.append([msg])
            i += 1

        selected = []
        count = 0
        for group in reversed(groups):
            if selected and count + len(group) > self.MAX_HISTORY_MESSAGES:
                break
            selected.insert(0, group)
            count += len(group)

        self.messages = [system_msg] + [msg for group in selected for msg in group]

    def _get_worker_tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for name in self.profile.tools:
            if name in list_static_tool_names():
                schemas.append(get_static_tool(name).get_openai_schema())
        return schemas
