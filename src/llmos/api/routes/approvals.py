import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from ...db.models import StepRecord, TaskRecord
from ...schemas.enums import ApprovalDecision, TaskState
from ...schemas.task import ApprovalIn, TaskOut

router = APIRouter()


def _get_session(request: Request):
    return request.app.state.session_factory()


def _find_awaiting_step(session, task: TaskRecord) -> "Optional[StepRecord]":
    """Return the step that is waiting for approval, or None."""
    for step in task.steps:
        if step.requires_approval and step.approval_decision is None:
            return step
    return None


@router.post("/{task_id}/approve", response_model=TaskOut)
def approve_step(task_id: str, body: ApprovalIn, request: Request):
    with _get_session(request) as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.state != TaskState.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail=f"Task is not AWAITING_APPROVAL, current state: {task.state}",
            )

        step = _find_awaiting_step(session, task)
        if step is None:
            raise HTTPException(status_code=409, detail="No step awaiting approval")

        step.approval_decision = ApprovalDecision.APPROVED
        task.state = TaskState.RUNNING
        task.updated_at = datetime.datetime.utcnow()
        session.commit()
        session.refresh(task)
        result = TaskOut.model_validate(task)

    # Unblock the worker thread
    event = request.app.state.approval_events.get(task_id)
    if event:
        event.set()

    return result


@router.post("/{task_id}/reject", response_model=TaskOut)
def reject_step(task_id: str, body: ApprovalIn, request: Request):
    with _get_session(request) as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.state != TaskState.AWAITING_APPROVAL:
            raise HTTPException(
                status_code=409,
                detail=f"Task is not AWAITING_APPROVAL, current state: {task.state}",
            )

        step = _find_awaiting_step(session, task)
        if step is None:
            raise HTTPException(status_code=409, detail="No step awaiting approval")

        step.approval_decision = ApprovalDecision.REJECTED
        task.state = TaskState.CANCELLED
        task.updated_at = datetime.datetime.utcnow()
        session.commit()
        session.refresh(task)
        result = TaskOut.model_validate(task)

    # Unblock the worker thread
    event = request.app.state.approval_events.get(task_id)
    if event:
        event.set()

    return result
