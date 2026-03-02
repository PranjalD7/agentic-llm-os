import uuid
import datetime

from sqlalchemy import (
    Column, String, Integer, Text, DateTime,
    ForeignKey, Boolean,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime.datetime:
    return datetime.datetime.utcnow()


class TaskRecord(Base):
    __tablename__ = "tasks"

    id         = Column(String, primary_key=True, default=_uuid)
    intent     = Column(Text, nullable=False)
    state      = Column(String, nullable=False, default="PENDING")
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    error_msg  = Column(Text, nullable=True)

    steps = relationship(
        "StepRecord",
        back_populates="task",
        order_by="StepRecord.order",
        cascade="all, delete-orphan",
    )


class StepRecord(Base):
    __tablename__ = "steps"

    id          = Column(String, primary_key=True, default=_uuid)
    task_id     = Column(String, ForeignKey("tasks.id"), nullable=False)
    order       = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    command     = Column(Text, nullable=False)
    risk_level  = Column(String, nullable=False)
    state       = Column(String, nullable=False, default="PENDING")

    requires_approval = Column(Boolean, default=False)
    approval_decision = Column(String, nullable=True)
    approval_reason   = Column(Text, nullable=True)

    stdout      = Column(Text, nullable=True)
    stderr      = Column(Text, nullable=True)
    exit_code   = Column(Integer, nullable=True)
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("TaskRecord", back_populates="steps")
