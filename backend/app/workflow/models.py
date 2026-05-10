from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class WorkflowStep(BaseModel):
    step_id: str
    tool_name: str
    args: dict
    param_args: Optional[dict] = None


class WorkflowVariable(BaseModel):
    name: str
    default: str = ""
    description: str = ""


class Workflow(BaseModel):
    id: str
    name: str
    description: str = ""
    created_at: str
    variables: List[WorkflowVariable] = []
    steps: List[WorkflowStep] = []
