"""Worker dispatch tools - Manager dispatches subagents for parallel execution."""
import asyncio
import time
import uuid
from contextvars import ContextVar, Token
from typing import Any, Callable, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult
from app.worker import WorkerSession, WORKER_PROFILES

_worker_event_callback_var: ContextVar[Optional[Callable[[Dict[str, Any]], Any]]] = ContextVar(
    "worker_event_callback",
    default=None,
)
_active_workers: Dict[str, Dict[str, tuple[WorkerSession, Optional[Callable[[Dict[str, Any]], Any]]]]] = {}


def set_worker_event_callback(cb: Optional[Callable[[Dict[str, Any]], Any]]) -> Token:
    return _worker_event_callback_var.set(cb)


def reset_worker_event_callback(token: Token) -> None:
    _worker_event_callback_var.reset(token)


def _emit_worker_event(event: Dict[str, Any]) -> None:
    cb = _worker_event_callback_var.get()
    if cb:
        cb(event)


def _register_worker(session_id: str, worker: WorkerSession) -> None:
    if not session_id:
        return
    _active_workers.setdefault(session_id, {})[worker.worker_id] = (
        worker,
        _worker_event_callback_var.get(),
    )


def _unregister_worker(session_id: str, worker_id: str) -> None:
    workers = _active_workers.get(session_id)
    if not workers:
        return
    workers.pop(worker_id, None)
    if not workers:
        _active_workers.pop(session_id, None)


def cancel_workers_for_session(session_id: str) -> None:
    workers = list(_active_workers.get(session_id, {}).values())
    for worker, cb in workers:
        worker.cancel()
        event = worker.cancel_event()
        if event and cb:
            cb(event)


class DispatchWorkerTool(BaseTool):
    name = "dispatch_worker"
    description = "Dispatch a single worker agent to execute a subtask. The worker is an independent AI agent with restricted tools. Use this to offload focused work."
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task description for the worker agent to execute."
            },
            "profile": {
                "type": "string",
                "enum": list(WORKER_PROFILES.keys()),
                "description": "Worker profile determining available tools. 'code' for coding tasks, 'general' for broader tasks.",
                "default": "code",
            },
            "model_id": {
                "type": "string",
                "description": "Model ID for the worker. Defaults to the configured default model.",
            },
            "context_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to inject as context into the worker's system prompt.",
            },
            "prior_context": {
                "type": "string",
                "description": "Output from previous workers (e.g. architect plan, prior summaries). Prepended to task so worker has full context.",
            },
        },
        "required": ["task"],
    }

    async def execute(
        self,
        task: str,
        profile: str = "code",
        model_id: str = "",
        context_files: Optional[List[str]] = None,
        prior_context: str = "",
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        from app.config import load_config
        if not model_id:
            model_id = load_config().settings.default_model

        full_task = task
        if prior_context:
            full_task = f"## Prior Work Context\n{prior_context[:3000]}\n\n## Your Task\n{task}"

        worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        worker = WorkerSession(
            worker_id=worker_id,
            task=full_task,
            profile_name=profile,
            model_id=model_id,
            context_files=context_files,
            run_id=run_id,
            parent_tool_call_id=tool_call_id,
        )

        started_at = time.time()
        events: List[Dict[str, Any]] = []
        final_result = ""

        _register_worker(session_id, worker)
        try:
            async for event in worker.run():
                events.append(event)
                _emit_worker_event(event)
                if event["type"] == "worker_done":
                    final_result = event["data"].get("result", "")
        finally:
            _unregister_worker(session_id, worker.worker_id)

        duration_ms = round((time.time() - started_at) * 1000)

        tool_call_summaries = ""
        for e in events:
            if e["type"] == "worker_tool_call":
                d = e["data"]
                tool_call_summaries += f"\n  [{d['name']}] {d.get('result', '')[:200]}"

        output = (
            f"Worker {worker_id} ({profile}) completed in {duration_ms}ms, {worker.iteration} iterations.\n"
            f"Result: {final_result}\n"
            f"Tool calls:{tool_call_summaries or ' none'}"
        )
        return ToolResult(output=output)


class DispatchParallelTool(BaseTool):
    name = "dispatch_parallel"
    description = "Dispatch MULTIPLE worker agents to execute subtasks IN PARALLEL. Workers run simultaneously. Use when tasks are independent. Each worker gets its own task and profile."
    parameters = {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "Task description for this worker."},
                        "profile": {"type": "string", "enum": list(WORKER_PROFILES.keys()), "default": "code"},
                        "model_id": {"type": "string", "description": "Optional model ID for this worker only."},
                        "agent_type": {"type": "string", "enum": ["coding", "personal"], "description": "Optional logical agent type for routing/trace context."},
                        "context_files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional files to inject into this worker's context.",
                        },
                        "prior_context": {"type": "string", "description": "Prior worker output or manager notes for this worker."},
                        "acceptance_criteria": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Concrete criteria the worker must satisfy in its result.",
                        },
                    },
                    "required": ["task"],
                },
                "description": "List of tasks, each dispatched to a separate worker.",
                "minItems": 1,
            },
            "model_id": {
                "type": "string",
                "description": "Model ID for ALL workers. Defaults to configured default model.",
            },
        },
        "required": ["tasks"],
    }

    async def execute(
        self,
        tasks: List[Dict[str, Any]],
        model_id: str = "",
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
    ) -> ToolResult:
        from app.config import load_config
        if not model_id:
            model_id = load_config().settings.default_model

        started_at = time.time()

        async def run_one(idx: int, task_spec: Dict[str, Any]) -> Dict[str, Any]:
            worker_id = f"worker_{uuid.uuid4().hex[:6]}_{idx}"
            profile_name = task_spec.get("profile", "code")
            worker_model = task_spec.get("model_id") or model_id
            worker_task = task_spec["task"]
            prior_context = task_spec.get("prior_context") or ""
            acceptance = task_spec.get("acceptance_criteria") or []
            agent_type = task_spec.get("agent_type") or "coding"
            if prior_context:
                worker_task = f"## Prior Work Context\n{str(prior_context)[:3000]}\n\n## Your Task\n{worker_task}"
            if acceptance:
                criteria = "\n".join(f"- {item}" for item in acceptance if item)
                worker_task = f"{worker_task}\n\n## Acceptance Criteria\n{criteria}"
            if agent_type:
                worker_task = f"## Agent Type\n{agent_type}\n\n{worker_task}"
            worker = WorkerSession(
                worker_id=worker_id,
                task=worker_task,
                profile_name=profile_name,
                model_id=worker_model,
                context_files=task_spec.get("context_files"),
                run_id=run_id,
                parent_tool_call_id=tool_call_id,
            )
            events: List[Dict[str, Any]] = []
            final = ""
            _register_worker(session_id, worker)
            try:
                async for event in worker.run():
                    events.append(event)
                    _emit_worker_event(event)
                    if event["type"] == "worker_done":
                        final = event["data"].get("result", "")
            finally:
                _unregister_worker(session_id, worker.worker_id)
            return {
                "worker_id": worker_id,
                "profile": profile_name,
                "model_id": worker_model,
                "agent_type": agent_type,
                "task": task_spec["task"],
                "result": final,
                "iterations": worker.iteration,
                "events": events,
            }

        all_results = await asyncio.gather(
            *(run_one(i, ts) for i, ts in enumerate(tasks)),
            return_exceptions=True,
        )

        total_duration_ms = round((time.time() - started_at) * 1000)

        output_parts = [f"Parallel dispatch complete in {total_duration_ms}ms:\n"]
        success_count = 0
        fail_count = 0

        for i, result_raw in enumerate(all_results):
            if isinstance(result_raw, Exception):
                fail_count += 1
                output_parts.append(f"  Worker {i}: FAILED - {result_raw}")
            else:
                result: Dict[str, Any] = result_raw  # type: ignore[assignment]
                success_count += 1
                output_parts.append(
                    f"  {result['worker_id']} ({result['profile']}, {result['model_id']}): "
                    f"{result['iterations']} iterations - {result['result'][:300]}"
                )

        output_parts.append(f"\n{success_count} succeeded, {fail_count} failed")
        return ToolResult(output="\n".join(output_parts))
