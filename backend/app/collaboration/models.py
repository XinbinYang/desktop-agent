from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


AgentOwner = Literal["personal", "coding", "worker"]
TaskMode = Literal["consult", "execute", "handoff"]
RunStatus = Literal["running", "completed", "failed", "cancelled"]
TaskStatus = Literal["pending", "running", "completed", "failed", "blocked", "cancelled"]


class ArtifactRef(BaseModel):
    id: str
    type: str = "text"
    title: str
    url: str = ""
    path: str = ""
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskPacket(BaseModel):
    goal: str
    mode: TaskMode = "consult"
    user_intent: str = ""
    product_intent: str = ""
    constraints: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    allowed_tools: List[str] = Field(default_factory=list)
    owner: AgentOwner = "coding"
    created_by: AgentOwner = "personal"


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
    source_agent: AgentOwner = "personal"
    target_agent: AgentOwner = "coding"
    mode: TaskMode = "consult"
    goal: str = ""
    project_path: str = ""
    task_ids: List[str] = Field(default_factory=list)
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    summary: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class CollaborationEvent(BaseModel):
    id: int = 0
    run_id: str
    task_id: str = ""
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
