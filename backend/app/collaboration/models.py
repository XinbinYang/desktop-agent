from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


AgentOwner = Literal["personal", "coding", "worker"]
TaskMode = Literal["consult", "execute", "handoff", "plan_then_execute", "critic", "verify_only"]
RunStatus = Literal["running", "waiting_clarification", "paused", "completed", "failed", "cancelled"]
TaskStatus = Literal[
    "pending",
    "running",
    "waiting_clarification",
    "completed",
    "failed",
    "blocked",
    "cancelled",
]


class ArtifactRef(BaseModel):
    id: str
    type: str = "text"
    title: str
    url: str = ""
    path: str = ""
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskBudget(BaseModel):
    max_iterations: int = 30
    max_seconds: int = 600
    max_input_tokens: int = 200_000
    on_exceed: Literal["escalate", "stop", "ask_user"] = "ask_user"


class TaskInvariant(BaseModel):
    """红线约束：违反即任务失败，需要明确告警。"""
    description: str
    detector: Optional[str] = None


class EvidenceEntry(BaseModel):
    """结构化证据账本条目，记录命令/测试/diff/review 的可验证事实。"""
    kind: Literal["command", "test", "diff", "review", "screenshot"]
    label: str
    command: str = ""
    exit_code: Optional[int] = None
    output_excerpt: str = ""  # 截取前 2KB
    output_ref: Optional[str] = None  # 大输出走 artifact id 引用


class TaskPacket(BaseModel):
    goal: str
    mode: TaskMode = "consult"
    user_intent: str = ""
    product_intent: str = ""
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    allowed_tools: List[str] = Field(default_factory=list)
    owner: str = "coding"  # str 支持未来专家注册，运行时由 registry 校验
    created_by: str = "personal"
    # P0 新增：强契约字段（全部有默认值，向后兼容）
    budget: TaskBudget = Field(default_factory=TaskBudget)
    invariants: List[TaskInvariant] = Field(default_factory=list)
    expected_output_schema: Optional[Dict[str, Any]] = None
    prior_attempts: List[str] = Field(default_factory=list)
    parent_task_id: Optional[str] = None
    correlation_key: Optional[str] = None


class ResultPacket(BaseModel):
    status: Literal["pass", "fail", "blocked"] = "pass"
    summary: str = ""
    details: str = ""
    changed_files: List[str] = Field(default_factory=list)
    tests_run: List[str] = Field(default_factory=list)
    verification_passed: Optional[bool] = None
    review_passed: Optional[bool] = None
    assumptions: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    # P0 新增：结构化结果字段（全部有默认值，向后兼容）
    confidence: float = 1.0
    needs_human_decision: List[str] = Field(default_factory=list)
    follow_up_tasks: List[TaskPacket] = Field(default_factory=list)
    evidence: List[EvidenceEntry] = Field(default_factory=list)
    cost: Dict[str, float] = Field(default_factory=dict)
    invariants_violated: List[str] = Field(default_factory=list)


class CollaborationTask(BaseModel):
    task_id: str
    run_id: str
    owner: AgentOwner = "coding"
    mode: TaskMode = "consult"
    status: TaskStatus = "pending"
    packet: TaskPacket
    result: Optional[ResultPacket] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class CollaborationRun(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus = "running"
    source_agent: str = "personal"
    target_agent: str = "coding"
    mode: TaskMode = "consult"
    goal: str = ""
    project_path: str = ""
    task_ids: List[str] = Field(default_factory=list)
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    summary: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    correlation_key: Optional[str] = None  # 跨 run 的语义关联


class CollaborationEvent(BaseModel):
    id: int = 0
    run_id: str
    task_id: str = ""
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
