import pytest
import json
from pathlib import Path

from app.workflow.models import Workflow, WorkflowStep, WorkflowVariable
from app.workflow.storage import save_workflow, load_workflow, list_workflows, delete_workflow, WORKFLOWS_DIR
from app.workflow.engine import WorkflowRecorder, WorkflowExecutor, _replace_variables


class TestVariableReplacement:
    def test_replace_in_string(self):
        assert _replace_variables("Hello ${name}", {"name": "World"}) == "Hello World"

    def test_replace_in_dict(self):
        result = _replace_variables({"url": "${base}/api", "key": "${key}"}, {"base": "http://localhost", "key": "secret"})
        assert result["url"] == "http://localhost/api"
        assert result["key"] == "secret"

    def test_missing_variable_unchanged(self):
        assert _replace_variables("${missing}", {}) == "${missing}"

    def test_replace_in_list(self):
        result = _replace_variables(["${a}", "${b}"], {"a": "1", "b": "2"})
        assert result == ["1", "2"]


class TestWorkflowRecorder:
    def test_record_and_stop(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.workflow.storage.WORKFLOWS_DIR", tmp_path)
        recorder = WorkflowRecorder(name="Test Workflow", description="A test")
        recorder.start()
        assert recorder.is_recording()

        recorder.record_step("screenshot", {})
        recorder.record_step("mouse_click", {"x": 100, "y": 200})
        recorder.record_step("workflow_list", {})  # 应被跳过

        workflow = recorder.stop()
        assert not recorder.is_recording()
        assert workflow.name == "Test Workflow"
        assert len(workflow.steps) == 2
        assert workflow.steps[0].tool_name == "screenshot"
        assert workflow.steps[1].tool_name == "mouse_click"

        # 验证已持久化
        loaded = load_workflow(workflow.id)
        assert loaded is not None
        assert loaded.name == "Test Workflow"


class TestWorkflowExecutor:
    @pytest.mark.asyncio
    async def test_execute_simple_workflow(self):
        workflow = Workflow(
            id="wf-test",
            name="Simple",
            created_at="2024-01-01T00:00:00",
            steps=[
                WorkflowStep(step_id="s1", tool_name="get_screen_size", args={}),
            ],
        )
        executor = WorkflowExecutor(workflow)
        events = []
        async for event in executor.run():
            events.append(event)

        assert events[0]["type"] == "step_start"
        assert events[0]["tool_name"] == "get_screen_size"
        assert events[1]["type"] == "step_end"
        assert events[1]["error"] == ""
        assert events[2]["type"] == "completed"

    @pytest.mark.asyncio
    async def test_execute_with_variables(self):
        workflow = Workflow(
            id="wf-test2",
            name="With Vars",
            created_at="2024-01-01T00:00:00",
            variables=[WorkflowVariable(name="url", default="https://example.com")],
            steps=[
                WorkflowStep(step_id="s1", tool_name="browser_navigate", args={"url": "${url}"}),
            ],
        )
        executor = WorkflowExecutor(workflow)
        events = []
        async for event in executor.run(variables={"url": "https://google.com"}):
            events.append(event)

        assert events[0]["args"]["url"] == "https://google.com"

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        workflow = Workflow(
            id="wf-test3",
            name="Error Test",
            created_at="2024-01-01T00:00:00",
            steps=[
                WorkflowStep(step_id="s1", tool_name="unknown_tool_xyz", args={}),
            ],
        )
        executor = WorkflowExecutor(workflow)
        events = []
        async for event in executor.run():
            events.append(event)

        assert events[0]["type"] == "step_start"
        assert events[1]["type"] == "step_end"
        assert "Unknown tool" in events[1]["error"] or "unknown_tool" in events[1]["error"]


class TestWorkflowStorage:
    def test_save_load_list_delete(self, tmp_path, monkeypatch):
        monkeypatch.setattr("app.workflow.storage.WORKFLOWS_DIR", tmp_path)
        wf = Workflow(
            id="wf-1",
            name="Test",
            created_at="2024-01-01T00:00:00",
            steps=[WorkflowStep(step_id="s1", tool_name="screenshot", args={})],
        )
        save_workflow(wf)
        assert len(list_workflows()) == 1

        loaded = load_workflow("wf-1")
        assert loaded is not None
        assert loaded.name == "Test"

        assert delete_workflow("wf-1") is True
        assert len(list_workflows()) == 0
        assert delete_workflow("wf-1") is False
