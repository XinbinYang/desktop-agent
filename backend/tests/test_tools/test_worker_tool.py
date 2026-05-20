"""Tests for dispatch_worker and dispatch_parallel tools."""
import pytest
from unittest.mock import MagicMock, patch

from app.message_utils import execute_tool
from app.tools.base import ToolResult
from app.tools.worker_tool import DispatchWorkerTool, DispatchParallelTool, reset_worker_event_callback, set_worker_event_callback
from app.worker import WorkerSession


@pytest.mark.asyncio
async def test_execute_tool_injects_session_model_id_context():
    class CaptureModelTool:
        async def execute(self, session_model_id: str = ""):
            return ToolResult(output=session_model_id)

    result = await execute_tool(
        "capture_model",
        {"session_model_id": "kimi-for-coding"},
        ["capture_model"],
        session_model_id="gpt-4o-mini",
        get_tool_fn=lambda _name: CaptureModelTool(),
    )

    assert result.result_text == "gpt-4o-mini"


class TestDispatchWorkerTool:
    @pytest.mark.asyncio
    async def test_dispatch_worker_basic(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Done: file created.",
                    "role": "assistant",
                }
            }]
        }
        tool = DispatchWorkerTool()
        events = []
        token = set_worker_event_callback(events.append)
        try:
            result = await tool.execute(
                task="Write hello.py", profile="code", model_id="gpt-4o",
                run_id="run1", tool_call_id="parent1",
            )
        finally:
            reset_worker_event_callback(token)
        assert "Worker worker_" in result.output
        assert "completed" in result.output
        assert "Done: file created" in result.output
        assert events[0]["type"] == "worker_start"
        assert events[0]["data"]["parent_tool_call_id"] == "parent1"
        assert events[0]["data"]["run_id"] == "run1"

    @pytest.mark.asyncio
    async def test_dispatch_worker_with_tool_calls(self, mock_litellm_with_tool_call):
        mock_litellm_with_tool_call.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_screen_size",
                            "arguments": "{}",
                        }
                    }]
                }
            }]
        }
        tool = DispatchWorkerTool()
        result = await tool.execute(
            task="Check screen size", profile="general", model_id="gpt-4o",
        )
        assert "get_screen_size" in result.output

    @pytest.mark.asyncio
    async def test_dispatch_worker_invalid_profile(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Done.",
                    "role": "assistant",
                }
            }]
        }
        tool = DispatchWorkerTool()
        result = await tool.execute(
            task="Test", profile="nonexistent", model_id="gpt-4o",
        )
        # Should fall back to 'general' profile
        assert "Worker" in result.output

    @pytest.mark.asyncio
    async def test_dispatch_worker_passes_agent_type_to_session(self):
        seen = []

        async def replacement_run(self):
            seen.append(self.agent_type)
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Task completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchWorkerTool()
            result = await tool.execute(
                task="Summarize notes",
                profile="general",
                agent_type="personal",
                model_id="gpt-4o",
            )

        assert "Worker" in result.output
        assert seen == ["personal"]

    @pytest.mark.asyncio
    async def test_dispatch_worker_inherits_session_model_when_model_omitted(self):
        seen = []

        async def replacement_run(self):
            seen.append(self.model_id)
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Task completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchWorkerTool()
            result = await tool.execute(
                task="Summarize notes",
                profile="general",
                session_model_id="gpt-4o",
            )

        assert "Worker" in result.output
        assert seen == ["gpt-4o"]

    @pytest.mark.asyncio
    async def test_dispatch_worker_failed_done_returns_tool_error(self):
        async def replacement_run(self):
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "failed",
                "result": "[Worker model error: TimeoutError]",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchWorkerTool()
            result = await tool.execute(task="Fail task", profile="code", model_id="gpt-4o")

        assert result.error
        assert "failed" in result.output
        assert "Worker model error" in result.error


class TestDispatchParallelTool:
    @pytest.mark.asyncio
    async def test_dispatch_parallel_two_tasks(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Task done.",
                    "role": "assistant",
                }
            }]
        }
        tool = DispatchParallelTool()
        result = await tool.execute(
            tasks=[
                {"task": "Task A", "profile": "code"},
                {"task": "Task B", "profile": "code"},
            ],
            model_id="gpt-4o",
        )
        assert "2 succeeded" in result.output
        assert "0 failed" in result.output

    @pytest.mark.asyncio
    async def test_dispatch_parallel_partial_failure(self):
        """When a worker crashes with an unhandled exception, the parallel
        dispatcher counts it as a failure and reports successes separately."""

        call_count = [0]

        async def replacement_run(self):
            call_count[0] += 1
            if call_count[0] == 1:
                # First worker: yields done event then crashes
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "failed",
                    "result": "[Worker crashed]",
                    "iterations": 0,
                    "duration_ms": 0,
                }}
                raise RuntimeError("Worker crashed unexpectedly")
            else:
                # Second worker: completes normally
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "completed",
                    "result": "Task completed successfully.",
                    "iterations": 1,
                    "duration_ms": 10,
                }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(tasks=[
                {"task": "Task A", "profile": "code"},
                {"task": "Task B", "profile": "code"},
            ])

        assert "1 succeeded" in result.output
        assert "1 failed" in result.output
        assert result.error

    @pytest.mark.asyncio
    async def test_dispatch_parallel_worker_done_failed_counts_as_failure(self):
        """A worker can report failure without throwing; that must not be
        counted as a successful dispatch."""

        call_count = [0]

        async def replacement_run(self):
            call_count[0] += 1
            if call_count[0] == 1:
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "failed",
                    "result": "[Worker model error: TimeoutError]",
                    "iterations": 1,
                    "duration_ms": 10,
                }}
            else:
                yield {"type": "worker_done", "data": {
                    "worker_id": self.worker_id,
                    "status": "completed",
                    "result": "Task completed successfully.",
                    "iterations": 1,
                    "duration_ms": 10,
                }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(tasks=[
                {"task": "Task A", "profile": "code"},
                {"task": "Task B", "profile": "code"},
            ])

        assert "1 succeeded" in result.output
        assert "1 failed" in result.output
        assert "(code," in result.output
        assert "failed): 1 iterations" in result.output
        assert result.error

    @pytest.mark.asyncio
    async def test_dispatch_parallel_acceptance_fail_counts_as_failure(self):
        async def replacement_run(self):
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Could not verify.\nACCEPTANCE: FAIL",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(tasks=[{"task": "Task A", "profile": "code"}])

        assert "0 succeeded" in result.output
        assert "1 failed" in result.output
        assert result.error

    @pytest.mark.asyncio
    async def test_dispatch_parallel_rejects_tasks_above_configured_limit(self):
        tool = DispatchParallelTool()
        tasks = [{"task": f"Task {idx}", "profile": "code"} for idx in range(4)]

        with patch("app.tools.worker_tool.get_parallel_worker_limit", return_value=3):
            result = await tool.execute(tasks=tasks, model_id="gpt-4o")

        assert result.error
        assert "requested 4 workers" in result.output
        assert "configured maximum is 3" in result.output
        assert result.metadata["requested_workers"] == 4
        assert result.metadata["worker_limit"] == 3

    def test_dispatch_parallel_schema_exposes_configured_limit(self):
        tool = DispatchParallelTool()

        with patch("app.tools.worker_tool.get_parallel_worker_limit", return_value=2):
            schema = tool.get_openai_schema()

        tasks_schema = schema["function"]["parameters"]["properties"]["tasks"]
        assert tasks_schema["maxItems"] == 2
        assert "Hard maximum: 2" in tasks_schema["description"]

    @pytest.mark.asyncio
    async def test_dispatch_parallel_per_task_model_context_and_acceptance(self):
        from app.config import list_all_models
        model_ids = [m["id"] for m in list_all_models()]
        first_model = model_ids[0]
        second_model = model_ids[-1]
        seen = []

        async def replacement_run(self):
            seen.append({
                "model_id": self.model_id,
                "profile": self.profile.name,
                "task": self.task,
                "context_files": self._context_files,
                "agent_type": self.agent_type,
            })
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Task completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(
                tasks=[
                    {
                        "task": "Explore API",
                        "profile": "explorer",
                        "model_id": first_model,
                        "agent_type": "coding",
                        "context_files": ["backend/app/main.py"],
                        "prior_context": "Manager notes",
                        "acceptance_criteria": ["Return key routes"],
                    },
                    {
                        "task": "Review diff",
                        "profile": "reviewer",
                        "model_id": second_model,
                    },
                ],
                model_id=first_model,
            )

        assert "2 succeeded" in result.output
        assert seen[0]["model_id"] == first_model
        assert seen[0]["profile"] == "explorer"
        assert "Manager notes" in seen[0]["task"]
        assert "Return key routes" in seen[0]["task"]
        assert seen[0]["context_files"] == ["backend/app/main.py"]
        assert seen[0]["agent_type"] == "coding"
        assert seen[1]["model_id"] == second_model
        assert seen[1]["profile"] == "reviewer"
        assert seen[1]["agent_type"] == "coding"

    @pytest.mark.asyncio
    async def test_dispatch_parallel_inherits_session_model_when_model_omitted(self):
        seen = []

        async def replacement_run(self):
            seen.append(self.model_id)
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Task completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(
                tasks=[
                    {"task": "Task A", "profile": "code"},
                    {"task": "Task B", "profile": "reviewer"},
                ],
                session_model_id="gpt-4o-mini",
            )

        assert "2 succeeded" in result.output
        assert seen == ["gpt-4o-mini", "gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_dispatch_parallel_task_model_overrides_session_model(self):
        seen = []

        async def replacement_run(self):
            seen.append(self.model_id)
            yield {"type": "worker_done", "data": {
                "worker_id": self.worker_id,
                "status": "completed",
                "result": "Task completed.",
                "iterations": 1,
                "duration_ms": 10,
            }}

        with patch.object(WorkerSession, "run", new=replacement_run):
            tool = DispatchParallelTool()
            result = await tool.execute(
                tasks=[
                    {"task": "Task A", "profile": "code", "model_id": "gpt-4o"},
                    {"task": "Task B", "profile": "reviewer"},
                ],
                session_model_id="gpt-4o-mini",
            )

        assert "2 succeeded" in result.output
        assert seen == ["gpt-4o", "gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_dispatch_parallel_empty_tasks(self, mock_litellm):
        tool = DispatchParallelTool()
        result = await tool.execute(tasks=[])
        assert result.error
        assert "requires at least one task" in result.output
