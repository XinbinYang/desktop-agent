from typing import Any, Dict, Optional

from app.tools.base import BaseTool, ToolResult
from app.workflow.models import Workflow
from app.workflow.engine import WorkflowRecorder

# 全局录制器字典：session_id -> WorkflowRecorder
_recorders: dict[str, WorkflowRecorder] = {}


def get_recorder(session_id: str) -> Optional[WorkflowRecorder]:
    return _recorders.get(session_id)


def set_recorder(session_id: str, recorder: WorkflowRecorder) -> None:
    _recorders[session_id] = recorder


def clear_recorder(session_id: str):
    _recorders.pop(session_id, None)


class WorkflowRecordTool(BaseTool):
    name = "workflow_record"
    description = "开始录制当前会话的工具调用序列。录制期间所有成功的工具调用（除 workflow_* 自身外）都会被捕获。"
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "工作流名称"},
            "description": {"type": "string", "description": "工作流描述"}
        },
        "required": ["name"]
    }

    async def execute(self, name: str, description: str = "", session_id: str = "") -> ToolResult:
        if not session_id:
            return ToolResult(error="session_id 缺失，无法录制")
        from app.workflow.engine import create_recorder
        recorder = create_recorder(name, description)
        recorder.start()
        set_recorder(session_id, recorder)
        return ToolResult(output=f"开始录制工作流: {name}。后续的工具调用将被捕获，调用 workflow_stop 停止录制。")


class WorkflowStopTool(BaseTool):
    name = "workflow_stop"
    description = "停止录制并保存工作流。"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, session_id: str = "") -> ToolResult:
        recorder = get_recorder(session_id) if session_id else None
        if not recorder:
            return ToolResult(error="当前没有正在录制的工作流")
        workflow = recorder.stop()
        clear_recorder(session_id)
        return ToolResult(
            output=f"工作流已保存: {workflow.name} (ID: {workflow.id}, 共 {len(workflow.steps)} 步)"
        )


class WorkflowListTool(BaseTool):
    name = "workflow_list"
    description = "列出所有已保存的工作流。"
    parameters = {"type": "object", "properties": {}}

    async def execute(self) -> ToolResult:
        from app.workflow.engine import get_all_workflows
        workflows = get_all_workflows()
        if not workflows:
            return ToolResult(output="暂无已保存的工作流。")
        lines = [f"共 {len(workflows)} 个工作流："]
        for w in workflows:
            lines.append(f"- {w.name} (ID: {w.id}, {len(w.steps)} 步) {w.description or ''}")
        return ToolResult(output="\n".join(lines))


class WorkflowRunTool(BaseTool):
    name = "workflow_run"
    description = "运行指定的工作流。可通过 variables 传入变量值替换工作流中的 ${var_name} 占位符。"
    parameters = {
        "type": "object",
        "properties": {
            "workflow_id": {"type": "string", "description": "工作流 ID"},
            "variables": {
                "type": "object",
                "description": "变量值映射，如 {\"target_url\": \"https://example.com\"}",
                "default": {}
            }
        },
        "required": ["workflow_id"]
    }

    async def execute(self, workflow_id: str, variables: Optional[Dict[str, Any]] = None) -> ToolResult:
        from app.workflow.engine import get_workflow, WorkflowExecutor
        workflow = get_workflow(workflow_id)
        if not workflow:
            return ToolResult(error=f"未找到工作流: {workflow_id}")
        executor = WorkflowExecutor(workflow)
        results = []
        async for event in executor.run(variables=variables or {}):
            if event["type"] == "step_start":
                results.append(f"[{event['progress']}] 执行 {event['tool_name']}...")
            elif event["type"] == "step_end":
                if event.get("error"):
                    results.append(f"  ✗ 错误: {event['error']}")
                else:
                    results.append(f"  ✓ 完成")
            elif event["type"] == "completed":
                results.append("工作流执行完毕。")
        return ToolResult(output="\n".join(results))
