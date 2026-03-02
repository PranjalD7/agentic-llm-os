import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import Session

from ...db.models import TaskRecord
from ...schemas.enums import TaskState
from ...schemas.task import TaskCreate, TaskOut

router = APIRouter()


def _get_session(request: Request) -> Session:
    return request.app.state.session_factory()


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, request: Request):
    with _get_session(request) as session:
        task = TaskRecord(intent=body.intent)
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id

    request.app.state.task_queue.put(task_id)

    with _get_session(request) as session:
        task = session.get(TaskRecord, task_id)
        return TaskOut.model_validate(task)


@router.get("", response_model=List[TaskOut])
def list_tasks(request: Request):
    with _get_session(request) as session:
        tasks = (
            session.query(TaskRecord)
            .order_by(TaskRecord.created_at.desc())
            .limit(50)
            .all()
        )
        return [TaskOut.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, request: Request):
    with _get_session(request) as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return TaskOut.model_validate(task)


@router.delete("/{task_id}")
def cancel_task(task_id: str, request: Request):
    cancellable = {TaskState.PENDING, TaskState.RUNNING, TaskState.AWAITING_APPROVAL}

    with _get_session(request) as session:
        task = session.get(TaskRecord, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.state not in {s.value for s in cancellable}:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel task in state {task.state}",
            )
        task.state = TaskState.CANCELLED
        task.updated_at = datetime.datetime.utcnow()
        session.commit()

    # Signal worker if it's waiting for approval
    event = request.app.state.approval_events.get(task_id)
    if event:
        event.set()

    return {"ok": True}
