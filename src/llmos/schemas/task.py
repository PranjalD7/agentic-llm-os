from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .enums import ApprovalDecision, RiskLevel, StepState, TaskState


class StepOut(BaseModel):
    id: str
    order: int
    description: str
    command: str
    risk_level: RiskLevel
    state: StepState
    requires_approval: bool
    approval_decision: Optional[ApprovalDecision] = None
    approval_reason: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TaskOut(BaseModel):
    id: str
    intent: str
    state: TaskState
    created_at: datetime
    updated_at: datetime
    error_msg: Optional[str] = None
    steps: List[StepOut] = []

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    intent: str = Field(..., min_length=3, max_length=1000)


class ApprovalIn(BaseModel):
    decision: ApprovalDecision
    comment: Optional[str] = None
