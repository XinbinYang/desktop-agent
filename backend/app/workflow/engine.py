import copy
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from app.workflow.models import Workflow, WorkflowStep, WorkflowVariable
from app.workflow.storage import save_workflow, load_workflow, list_workflows, delete_workflow
from app.tools.base import ToolResult

_VARIABLE_PATTERN = re.compile(r"\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _replace_variables(text_or_dict: Any, variables: Dict[str, str]) -> Any:
    """递归替换字符串中的 ${var_name} 变量。"""
    if isinstance(text_or_dict, str):
        def replacer(m):
            var_name = m.group(1)
            return variables.get(var_name, m.group(0))
        return _VARIABLE_PATTERN.sub(replacer, text_or_dict)
    elif isinstance(text_or_dict, dict):
        return {k: _replace_variables(v, variables) for k, v in text_or_dict.items()}
    elif isinstance(text_or_dict, list):
        return [_replace_variables(item, variables) for item in text_or_dict]
    return text_or_dict


class WorkflowRecorder:
    """工作流录制器：在 AgentSession 中捕获工具调用序列。"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._recording = False

    def start(self):
        self._recording = True
        self.steps = []

    def stop(self) -> Workflow:
        self._recording = False
        workflow = Workflow(
            id=f"wf-{uuid.uuid4().hex[:12]}",
            name=self.name,
            description=self.description,
            created_at=datetime.now(timezone.utc).isoformat(),
            steps=copy.deepcopy(self.steps),
        )
        save_workflow(workflow)
        return workflow

    def record_step(self, tool_name: str, args: dict):
        if not self._recording:
            return
        # 跳过工作流自身的工具，避免循环
        if tool_name.startswith("workflow_"):
            return
        self.steps.append(WorkflowStep(
            step_id=f"step-{len(self.steps) + 1}",
            tool_name=tool_name,
            args=copy.deepcopy(args),
        ))

    def is_recording(self) -> bool:
        return self._recording


class WorkflowExecutor:
    """工作流执行器：回放已保存的工作流。"""

    def __init__(self, workflow: Workflow):
        self.workflow = workflow

    async def run(
        self,
        variables: Optional[Dict[str, str]] = None,
        on_step_start: Optional[Callable[..., Any]] = None,
        on_step_end: Optional[Callable[..., Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行工作流，yield 每一步的结果。"""
        vars_dict = variables or {}
        # 填充默认值
        for v in self.workflow.variables:
            if v.name not in vars_dict:
                vars_dict[v.name] = v.default

        total = len(self.workflow.steps)
        for i, step in enumerate(self.workflow.steps):
            step_num = i + 1
            step_vars = vars_dict.copy()

            # 参数替换
            args = _replace_variables(step.args, step_vars)
            if step.param_args:
                args = _replace_variables(step.param_args, step_vars)

            if on_step_start:
                on_step_start(step.step_id, step.tool_name, args)

            yield {
                "type": "step_start",
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "args": args,
                "progress": f"{step_num}/{total}",
            }

            try:
                from app.tools import get_tool
                tool = get_tool(step.tool_name)
                result = await tool.execute(**args)
                yield {
                    "type": "step_end",
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "result": result.to_text(),
                    "error": result.error,
                    "progress": f"{step_num}/{total}",
                }
            except Exception as e:
                yield {
                    "type": "step_end",
                    "step_id": step.step_id,
                    "tool_name": step.tool_name,
                    "result": "",
                    "error": str(e),
                    "progress": f"{step_num}/{total}",
                }
                # 默认遇到错误停止
                break

            if on_step_end:
                on_step_end(step.step_id, step.tool_name, result)

        yield {"type": "completed", "workflow_id": self.workflow.id}


# ====== 便捷函数 ======

def create_recorder(name: str, description: str = "") -> WorkflowRecorder:
    return WorkflowRecorder(name, description)


def get_workflow(workflow_id: str) -> Optional[Workflow]:
    return load_workflow(workflow_id)


def get_all_workflows() -> List[Workflow]:
    return list_workflows()


def remove_workflow(workflow_id: str) -> bool:
    return delete_workflow(workflow_id)
