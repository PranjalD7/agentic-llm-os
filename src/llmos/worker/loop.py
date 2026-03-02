import datetime
import logging
import queue
import threading
from typing import Dict

from ..db.models import StepRecord, TaskRecord
from ..executor.runner import Executor
from ..planner.llm import LLMPlanner
from ..policy.engine import PolicyEngine
from ..schemas.enums import RiskLevel, TaskState

logger = logging.getLogger("llmos.worker")


class WorkerLoop:
    """
    Background thread that processes tasks from the queue.

    Flow per task:
      PENDING → PLANNING → (policy check all steps) → RUNNING
        → for each step:
            RISKY step  → AWAITING_APPROVAL (blocks on threading.Event)
              APPROVED  → execute
              REJECTED  → CANCELLED
            SAFE step   → execute immediately
            exit != 0   → FAILED (remaining steps SKIPPED)
        → all steps done → SUCCESS
    """

    def __init__(
        self,
        session_factory,
        executor: Executor,
        planner: LLMPlanner,
        policy_engine: PolicyEngine,
        task_queue: queue.Queue,
        approval_events: Dict[str, threading.Event],
        approval_timeout_seconds: int = 3600,
    ):
        self.session_factory = session_factory
        self.executor = executor
        self.planner = planner
        self.policy_engine = policy_engine
        self.task_queue = task_queue
        self.approval_events = approval_events
        self.approval_timeout = approval_timeout_seconds

    def run(self):
        """Entry point — run this in a daemon thread."""
        logger.info("Worker started")
        while True:
            task_id = self.task_queue.get(block=True)
            logger.info(f"Picked up task {task_id}")
            try:
                self._process_task(task_id)
            except Exception as e:
                logger.exception(f"Unhandled error processing task {task_id}: {e}")
                self._mark_failed(task_id, f"Internal worker error: {e}")
            finally:
                self.task_queue.task_done()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _mark_failed(self, task_id: str, reason: str):
        try:
            with self.session_factory() as session:
                task = session.get(TaskRecord, task_id)
                if task:
                    task.state = TaskState.FAILED
                    task.error_msg = reason
                    task.updated_at = datetime.datetime.utcnow()
                    session.commit()
        except Exception:
            logger.exception(f"Failed to mark task {task_id} as FAILED")

    def _process_task(self, task_id: str):
        with self.session_factory() as session:

            # ── 1. PENDING → PLANNING ────────────────────────────────────────
            task = session.get(TaskRecord, task_id)
            if task is None:
                logger.error(f"Task {task_id} not found in DB")
                return
            if task.state != TaskState.PENDING:
                logger.warning(f"Task {task_id} is {task.state}, expected PENDING — skipping")
                return

            task.state = TaskState.PLANNING
            task.updated_at = datetime.datetime.utcnow()
            session.commit()
            logger.info(f"Task {task_id}: PLANNING")

            # ── 2. Plan ──────────────────────────────────────────────────────
            step_specs = self.planner.plan(task.intent)
            logger.info(f"Task {task_id}: planned {len(step_specs)} step(s)")

            # ── 3. Policy — evaluate ALL steps before executing any ───────────
            verdicts = [self.policy_engine.evaluate(s.command) for s in step_specs]

            blocked = [
                (s, v) for s, v in zip(step_specs, verdicts)
                if v.risk_level == RiskLevel.BLOCKED
            ]
            if blocked:
                spec, verdict = blocked[0]
                task.state = TaskState.FAILED
                task.error_msg = f"BLOCKED: '{spec.command}' — {verdict.reason}"
                task.updated_at = datetime.datetime.utcnow()
                session.commit()
                logger.warning(f"Task {task_id}: BLOCKED at step {spec.order}")
                return

            # ── 4. Persist all steps to DB ────────────────────────────────────
            for spec, verdict in zip(step_specs, verdicts):
                step = StepRecord(
                    task_id=task_id,
                    order=spec.order,
                    description=spec.description,
                    command=verdict.transformed_command or spec.command,
                    risk_level=verdict.risk_level,
                    requires_approval=(verdict.risk_level == RiskLevel.RISKY),
                    approval_reason=verdict.reason,
                )
                session.add(step)
            session.commit()

            # ── 5. PLANNING → RUNNING ────────────────────────────────────────
            task.state = TaskState.RUNNING
            task.updated_at = datetime.datetime.utcnow()
            session.commit()
            logger.info(f"Task {task_id}: RUNNING")

            # ── 6. Execute steps in order ────────────────────────────────────
            # Refresh to get the newly created steps
            session.refresh(task)

            for step in task.steps:

                # ── Approval gate ─────────────────────────────────────────────
                if step.requires_approval and step.approval_decision is None:
                    task.state = TaskState.AWAITING_APPROVAL
                    task.updated_at = datetime.datetime.utcnow()
                    session.commit()
                    logger.info(f"Task {task_id}: AWAITING_APPROVAL for step {step.order}")

                    event = threading.Event()
                    self.approval_events[task_id] = event

                    granted = event.wait(timeout=self.approval_timeout)
                    self.approval_events.pop(task_id, None)

                    if not granted:
                        # Timeout waiting for human response
                        task.state = TaskState.FAILED
                        task.error_msg = f"Approval timeout for step {step.order}"
                        task.updated_at = datetime.datetime.utcnow()
                        self._skip_remaining(session, task)
                        session.commit()
                        return

                    # Re-read from DB to get the decision written by /approve or /reject
                    session.refresh(step)
                    session.refresh(task)

                    if step.approval_decision == "REJECTED":
                        task.state = TaskState.CANCELLED
                        task.updated_at = datetime.datetime.utcnow()
                        self._skip_remaining(session, task)
                        session.commit()
                        logger.info(f"Task {task_id}: CANCELLED (step {step.order} rejected)")
                        return

                    if task.state == TaskState.CANCELLED:
                        return

                    # APPROVED — set back to RUNNING and continue
                    task.state = TaskState.RUNNING
                    task.updated_at = datetime.datetime.utcnow()
                    session.commit()

                # ── Execute ───────────────────────────────────────────────────
                step.state = "RUNNING"
                step.started_at = datetime.datetime.utcnow()
                session.commit()

                result = self.executor.run(step.command)
                logger.info(
                    f"Task {task_id} step {step.order}: exit={result.exit_code} "
                    f"timeout={result.timed_out}"
                )

                step.stdout = result.stdout
                step.stderr = result.stderr
                step.exit_code = result.exit_code
                step.started_at = result.started_at
                step.finished_at = result.finished_at

                if result.timed_out or result.exit_code != 0:
                    step.state = "FAILED"
                    task.state = TaskState.FAILED
                    task.error_msg = (
                        f"Step {step.order} failed"
                        + (f" (timeout)" if result.timed_out else f" (exit {result.exit_code})")
                    )
                    task.updated_at = datetime.datetime.utcnow()
                    self._skip_remaining(session, task)
                    session.commit()
                    logger.warning(f"Task {task_id}: FAILED at step {step.order}")
                    return

                step.state = "SUCCESS"
                session.commit()

            # ── All steps succeeded ───────────────────────────────────────────
            task.state = TaskState.SUCCESS
            task.updated_at = datetime.datetime.utcnow()
            session.commit()
            logger.info(f"Task {task_id}: SUCCESS")

    def _skip_remaining(self, session, task: TaskRecord):
        for step in task.steps:
            if step.state == "PENDING":
                step.state = "SKIPPED"
