"""Worker dispatch tools - Manager dispatches subagents for parallel execution."""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolResult
from app.worker import WorkerSession, WORKER_PROFILES


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
        },
        "required": ["task"],
    }

    async def execute(self, task: str, profile: str = "code", model_id: str = "",
                      context_files: Optional[List[str]] = None) -> ToolResult:
        from app.config import load_config
        if not model_id:
            model_id = load_config().settings.default_model

        worker_id = f"worker_{uuid.uuid4().hex[:8]}"
        worker = WorkerSession(
            worker_id=worker_id,
            task=task,
            profile_name=profile,
            model_id=model_id,
            context_files=context_files,
        )

        started_at = time.time()
        events: List[Dict[str, Any]] = []
        final_result = ""

        async for event in worker.run():
            events.append(event)
            if event["type"] == "worker_done":
                final_result = event["data"].get("result", "")

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

    async def execute(self, tasks: List[Dict[str, str]], model_id: str = "") -> ToolResult:
        from app.config import load_config
        if not model_id:
            model_id = load_config().settings.default_model

        started_at = time.time()

        async def run_one(idx: int, task_spec: Dict[str, str]) -> Dict[str, Any]:
            worker_id = f"worker_{uuid.uuid4().hex[:6]}_{idx}"
            profile_name = task_spec.get("profile", "code")
            worker = WorkerSession(
                worker_id=worker_id,
                task=task_spec["task"],
                profile_name=profile_name,
                model_id=model_id,
            )
            events: List[Dict[str, Any]] = []
            final = ""
            async for event in worker.run():
                events.append(event)
                if event["type"] == "worker_done":
                    final = event["data"].get("result", "")
            return {
                "worker_id": worker_id,
                "profile": profile_name,
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

        for i, result in enumerate(all_results):
            if isinstance(result, Exception):
                fail_count += 1
                output_parts.append(f"  Worker {i}: FAILED - {result}")
            else:
                success_count += 1
                output_parts.append(
                    f"  {result['worker_id']} ({result['profile']}): "
                    f"{result['iterations']} iterations - {result['result'][:300]}"
                )

        output_parts.append(f"\n{success_count} succeeded, {fail_count} failed")
        return ToolResult(output="\n".join(output_parts))
