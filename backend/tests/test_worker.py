"""Tests for WorkerSession - lightweight worker agent."""
import pytest

from app.worker import WorkerSession, WORKER_PROFILES


class TestWorkerSession:
    def test_worker_profile_defaults(self):
        profile = WORKER_PROFILES["code"]
        assert profile.name == "code"
        assert "file_read" in profile.tools
        assert "dispatch_worker" not in profile.tools
        assert profile.max_iterations == 15

    def test_worker_init_builds_system_and_task_messages(self):
        worker = WorkerSession(
            worker_id="w1",
            task="Write a test",
            profile_name="code",
            model_id="gpt-4o",
        )
        assert len(worker.messages) == 2
        assert worker.messages[0]["role"] == "system"
        assert "Task: Write a test" in worker.messages[1]["content"]

    def test_worker_init_with_context_files(self):
        worker = WorkerSession(
            worker_id="w1",
            task="Fix tests",
            profile_name="code",
            model_id="gpt-4o",
            context_files=["src/a.py", "tests/test_a.py"],
        )
        assert "src/a.py" in worker.messages[1]["content"]
        assert "tests/test_a.py" in worker.messages[1]["content"]

    @pytest.mark.asyncio
    async def test_worker_completes_with_content(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Task completed successfully.",
                    "role": "assistant",
                }
            }]
        }
        worker = WorkerSession("w1", "Say hello", "code", "gpt-4o")
        events = []
        async for event in worker.run():
            events.append(event)
        assert events[-1]["type"] == "worker_done"
        assert events[-1]["data"]["status"] == "completed"
        assert "completed" in events[-1]["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_cancelled(self):
        worker = WorkerSession("w1", "Long task", "code", "gpt-4o")
        worker.cancel()
        events = []
        async for event in worker.run():
            events.append(event)
        assert events[0]["type"] == "worker_done"
        assert events[0]["data"]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_worker_rejects_restricted_tool(self, mock_litellm_with_tool_call):
        mock_litellm_with_tool_call.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "dispatch_worker",
                            "arguments": '{"task": "test"}',
                        }
                    }]
                }
            }]
        }
        worker = WorkerSession("w1", "Try dispatch", "code", "gpt-4o")
        events = []
        async for event in worker.run():
            events.append(event)
        tool_events = [e for e in events if e["type"] == "worker_tool_call"]
        assert len(tool_events) > 0
        assert "not available" in tool_events[0]["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_stale_detection(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "",
                    "role": "assistant",
                }
            }]
        }
        worker = WorkerSession("w1", "Empty task", "code", "gpt-4o")
        worker.STALE_THRESHOLD = 1
        events = []
        async for event in worker.run():
            events.append(event)
        done_event = events[-1]
        assert done_event["type"] == "worker_done"
        assert done_event["data"]["status"] == "failed"
        assert "stalled" in done_event["data"]["result"]

    @pytest.mark.asyncio
    async def test_worker_max_iterations(self, mock_litellm):
        mock_litellm.return_value.model_dump.return_value = {
            "choices": [{
                "message": {
                    "content": "Working...",
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
        worker = WorkerSession("w1", "Endless task", "code", "gpt-4o")
        worker.profile.max_iterations = 2
        events = []
        async for event in worker.run():
            events.append(event)
        done = events[-1]
        assert done["type"] == "worker_done"
        assert done["data"]["status"] == "max_iterations_reached"
