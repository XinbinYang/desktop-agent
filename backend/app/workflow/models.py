from datetime import datetime, timezone

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    variables: List[WorkflowVariable] = Field(default_factory=list)
    steps: List[WorkflowStep] = Field(default_factory=list)


class PlanQuestionOption(BaseModel):
    id: str
    label: str


class PlanQuestion(BaseModel):
    id: str
    prompt: str
    options: List[PlanQuestionOption]
    allow_multiple: bool = False


class PlanTodo(BaseModel):
    id: str
    title: str
    status: Literal["pending", "in_progress", "completed", "blocked", "cancelled"] = "pending"
    depends_on: List[str] = Field(default_factory=list)
    owner: str = "agent"
    parallel_group: Optional[str] = None
    acceptance_criteria: str = ""


class PlanStep(BaseModel):
    id: str
    title: str
    details: str = ""
    depends_on: List[str] = Field(default_factory=list)
    parallel_group: Optional[str] = None


class PlanDraft(BaseModel):
    goal: str = ""
    context: str = ""
    assumptions: List[str] = Field(default_factory=list)
    steps: List[PlanStep] = Field(default_factory=list)
    todos: List[PlanTodo] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    critical_files: List[Dict[str, str]] = Field(default_factory=list)


_VALID_TRANSITIONS: Dict[str, set[str]] = {
    "idle": {"clarifying", "planning"},
    "clarifying": {"planning", "awaiting_decision", "awaiting_approval", "idle"},
    "planning": {"awaiting_decision", "awaiting_approval", "idle"},
    "awaiting_decision": {"planning", "awaiting_approval", "idle"},
    "awaiting_approval": {"approved_waiting_build", "executing", "clarifying", "idle"},
    "approved_waiting_build": {"executing", "idle"},
    "executing": {"completed", "idle"},
    "completed": {"idle"},
}


class PlanState(BaseModel):
    mode: Literal["agent", "plan"] = "agent"
    phase: Literal[
        "idle",
        "clarifying",
        "planning",
        "awaiting_decision",
        "awaiting_approval",
        "approved_waiting_build",
        "executing",
        "completed",
    ] = "idle"
    draft: str = ""
    goal: str = ""
    questions: List[PlanQuestion] = Field(default_factory=list)
    todos: List[PlanTodo] = Field(default_factory=list)
    decisions: Dict[str, List[str]] = Field(default_factory=dict)
    decision_notes: Dict[str, str] = Field(default_factory=dict)
    structured_plan: Optional[PlanDraft] = None
    approved: bool = False
    # True while the user must answer clarification questions before a full structured plan exists.
    pending_clarification: bool = False
    # Path to the rendered markdown plan file on disk (relative to runtime_dir).
    plan_file_path: Optional[str] = None
    # Prior versions of the plan file (for iteration history).
    plan_file_versions: List[str] = Field(default_factory=list)
    # Research notes gathered by the LLM during exploration phase.
    research_notes: str = ""

    def transition_to(self, new_phase: str) -> bool:
        valid = _VALID_TRANSITIONS.get(self.phase, set())
        if new_phase not in valid:
            return False
        self.phase = new_phase
        return True
