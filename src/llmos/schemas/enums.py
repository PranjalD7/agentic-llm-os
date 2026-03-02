from enum import Enum


class TaskState(str, Enum):
    PENDING           = "PENDING"
    PLANNING          = "PLANNING"
    RUNNING           = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUCCESS           = "SUCCESS"
    FAILED            = "FAILED"
    CANCELLED         = "CANCELLED"


class StepState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"
    SKIPPED = "SKIPPED"


class RiskLevel(str, Enum):
    SAFE    = "SAFE"
    RISKY   = "RISKY"
    BLOCKED = "BLOCKED"


class ApprovalDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
