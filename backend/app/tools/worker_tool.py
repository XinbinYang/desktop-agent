"""Worker dispatch tools - Manager dispatches subagents for parallel execution."""
import asyncio
from copy import deepcopy
import time
import uuid
from contextvars import ContextVar, Token
from typing import Any, Callable, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult
from app.worker import WorkerSession, WORKER_PROFILES, format_worker_exception

_runtime_event_callback_var: ContextVar[Optional[Callable[[Dict[str, Any]], Any]]] = ContextVar(
    "runtime_event_callback",
    default=None,
)
_active_workers: Dict[str, Dict[str, tuple[WorkerSession, Optional[Callable[[Dict[str, Any]], Any]]]]] = {}

# Map worker profile names to team_role labels for frontend visibility.
PROFILE_TO_ROLE: dict[str, str] = {
    "explorer": "explorer",
    "architect": "architect",
    "code": "editor",
    "code-expert": "editor",
    "tdd-worker": "editor",
    "debugger": "verifier",
    "code-reviewer": "reviewer",
}


def set_runtime_event_callback(cb: Optional[Callable[[Dict[str, Any]], Any]]) -> Token:
    return _runtime_event_callback_var.set(cb)


def reset_runtime_event_callback(token: Token) -> None:
    _runtime_event_callback_var.reset(token)


def emit_runtime_event(event: Dict[str, Any]) -> bool:
    cb = _runtime_event_callback_var.get()
    if not cb:
        return False
    cb(event)
    return True


def set_worker_event_callback(cb: Optional[Callable[[Dict[str, Any]], Any]]) -> Token:
    return set_runtime_event_callback(cb)


def reset_worker_event_callback(token: Token) -> None:
    reset_runtime_event_callback(token)


def _emit_worker_event(event: Dict[str, Any]) -> None:
    emit_runtime_event(event)


def _worker_completed_successfully(status: str, result: str) -> bool:
    if status != "completed":
        return False
    return "ACCEPTANCE: FAIL" not in result


def _coerce_worker_limit(value: Any, default: int = 3) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(16, limit))


def _resolve_worker_model(model_id: str, session_model_id: str, agent_type: str) -> str:
    explicit = str(model_id or "").strip()
    if explicit:
        return explicit
    inherited = str(session_model_id or "").strip()
    if inherited:
        return inherited
    from app.config import get_model_for_agent

    return get_model_for_agent(agent_type)


def get_parallel_worker_limit() -> int:
    """Return the user-visible maximum for dispatch_parallel.

    ``settings.max_parallel_agents`` is the setting shown in the UI. The older
    ``coding_agent.max_parallel_workers`` field remains a config default for
    coding behavior, but the dispatch tool must obey the visible global limit.
    """
    try:
        from app.config import load_config

        cfg = load_config()
        return _coerce_worker_limit(getattr(cfg.settings, "max_parallel_agents", 3))
    except Exception:
        return 3


def _register_worker(session_id: str, worker: WorkerSession) -> None:
    if not session_id:
        return
    _active_workers.setdefault(session_id, {})[worker.worker_id] = (
        worker,
        _runtime_event_callback_var.get(),
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
    description = (
        "Dispatch a single worker agent to execute a subtask. The worker is an independent AI agent "
        "with restricted tools. If model_id is omitted, the worker inherits the current session model."
    )
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
                "description": "Model ID for the worker. Defaults to the current session model.",
            },
            "context_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to inject as context into the worker's system prompt.",
            },
            "agent_type": {
                "type": "string",
                "enum": ["coding", "personal"],
                "description": "Logical agent type used for skill matching. Defaults to coding.",
                "default": "coding",
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
        agent_type: str = "coding",
        prior_context: str = "",
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
        session_model_id: str = "",
    ) -> ToolResult:
        model_id = _resolve_worker_model(model_id, session_model_id, agent_type)

        full_task = task
        if prior_context:
            full_task = f"## Prior Work Context\n{prior_context[:3000]}\n\n## Your Task\n{task}"

        worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        team_role = PROFILE_TO_ROLE.get(profile, "")
        worker = WorkerSession(
            worker_id=worker_id,
            task=full_task,
            profile_name=profile,
            model_id=model_id,
            context_files=context_files,
            run_id=run_id,
            parent_tool_call_id=tool_call_id,
            agent_type=agent_type,
            team_role=team_role,
        )

        started_at = time.time()
        events: List[Dict[str, Any]] = []
        final_result = ""
        final_status = "failed"
        final_iterations = 0

        _emit_worker_event({
            "type": "team_progress",
            "data": {"team_role": team_role, "phase": "running", "summary": f"Worker started ({profile})"},
        })
        _register_worker(session_id, worker)
        try:
            async for event in worker.run():
                events.append(event)
                _emit_worker_event(event)
                if event["type"] == "worker_done":
                    data = event.get("data") or {}
                    final_result = data.get("result", "")
                    final_status = data.get("status", final_status)
                    final_iterations = data.get("iterations", worker.iteration)
        finally:
            _unregister_worker(session_id, worker.worker_id)

        team_status = "done" if final_status == "completed" else "failed"
        _emit_worker_event({
            "type": "team_progress",
            "data": {"team_role": team_role, "phase": team_status, "summary": f"Worker finished ({final_status})"},
        })

        duration_ms = round((time.time() - started_at) * 1000)

        tool_call_summaries = ""
        for e in events:
            if e["type"] == "worker_tool_call":
                d = e["data"]
                tool_call_summaries += f"\n  [{d['name']}] {d.get('result', '')[:200]}"

        output = (
            f"Worker {worker_id} ({profile}) {final_status} in {duration_ms}ms, {final_iterations} iterations.\n"
            f"Result: {final_result}\n"
            f"Tool calls:{tool_call_summaries or ' none'}"
        )
        if not _worker_completed_successfully(final_status, final_result):
            return ToolResult(output=output, error=output)
        return ToolResult(output=output)


class DispatchParallelTool(BaseTool):
    name = "dispatch_parallel"
    description = (
        "Dispatch MULTIPLE worker agents to execute subtasks IN PARALLEL. Workers run simultaneously. "
        "Use only when tasks are independent. Never exceed the configured max parallel sub-agent count."
    )
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
                "description": "Model ID for ALL workers. Defaults to the current session model.",
            },
        },
        "required": ["tasks"],
    }

    def _parameters_with_limit(self) -> Dict[str, Any]:
        params = deepcopy(self.parameters)
        limit = get_parallel_worker_limit()
        tasks_schema = params["properties"]["tasks"]
        tasks_schema["maxItems"] = limit
        tasks_schema["description"] = (
            f"List of tasks, each dispatched to a separate worker. Hard maximum: {limit} tasks. "
            "If more work exists, merge related scopes or dispatch in later batches."
        )
        return params

    def get_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters_with_limit(),
            },
        }

    def get_anthropic_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._parameters_with_limit(),
        }

    async def execute(
        self,
        tasks: List[Dict[str, Any]],
        model_id: str = "",
        session_id: str = "",
        run_id: str = "",
        tool_call_id: str = "",
        session_model_id: str = "",
    ) -> ToolResult:
        model_id = _resolve_worker_model(model_id, session_model_id, "coding")

        if not tasks:
            msg = "[ERROR] dispatch_parallel requires at least one task."
            return ToolResult(output=msg, error=msg)

        worker_limit = get_parallel_worker_limit()
        requested_workers = len(tasks)
        if requested_workers > worker_limit:
            msg = (
                f"[ERROR] dispatch_parallel requested {requested_workers} workers, "
                f"but the configured maximum is {worker_limit}. "
                "Merge related scopes or dispatch the remaining work in a later batch."
            )
            return ToolResult(
                output=msg,
                error=msg,
                metadata={
                    "worker_limit": worker_limit,
                    "requested_workers": requested_workers,
                },
            )

        started_at = time.time()

        async def run_one(idx: int, task_spec: Dict[str, Any]) -> Dict[str, Any]:
            worker_id = f"worker_{uuid.uuid4().hex[:6]}_{idx}"
            profile_name = task_spec.get("profile", "code")
            worker_model = str(task_spec.get("model_id") or "").strip() or model_id
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
                agent_type=agent_type,
                team_role=PROFILE_TO_ROLE.get(profile_name, ""),
            )
            events: List[Dict[str, Any]] = []
            final = ""
            final_status = "failed"
            final_iterations = 0
            _register_worker(session_id, worker)
            try:
                async for event in worker.run():
                    events.append(event)
                    _emit_worker_event(event)
                    if event["type"] == "worker_done":
                        data = event.get("data") or {}
                        final = data.get("result", "")
                        final_status = data.get("status", final_status)
                        final_iterations = data.get("iterations", worker.iteration)
            except Exception as e:
                final_status = "failed"
                final = f"[Worker dispatch error: {format_worker_exception(e)}]"
                final_iterations = worker.iteration
                failed_event = worker._worker_event("worker_done", {
                    "status": final_status,
                    "result": final,
                    "iterations": final_iterations,
                    "duration_ms": round((time.time() - started_at) * 1000),
                })
                events.append(failed_event)
                _emit_worker_event(failed_event)
            finally:
                _unregister_worker(session_id, worker.worker_id)
            return {
                "worker_id": worker_id,
                "profile": profile_name,
                "model_id": worker_model,
                "agent_type": agent_type,
                "task": task_spec["task"],
                "result": final,
                "status": final_status,
                "iterations": final_iterations,
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
                status = result.get("status", "failed")
                worker_success = _worker_completed_successfully(status, str(result.get("result", "")))
                if worker_success:
                    success_count += 1
                else:
                    fail_count += 1
                output_parts.append(
                    f"  {result['worker_id']} ({result['profile']}, {result['model_id']}, {status}): "
                    f"{result['iterations']} iterations - {result['result'][:300]}"
                )

        output_parts.append(f"\n{success_count} succeeded, {fail_count} failed")
        output = "\n".join(output_parts)
        if fail_count:
            return ToolResult(output=output, error=output)
        return ToolResult(output=output)
