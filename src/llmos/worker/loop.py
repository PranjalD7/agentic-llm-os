import datetime
import logging
import queue
import threading
from typing import Dict, List

from ..db.models import StepRecord, TaskRecord
from ..executor.runner import Executor
from ..planner.llm import LLMPlanner
from ..policy.engine import PolicyEngine
from ..schemas.enums import RiskLevel, TaskState

logger = logging.getLogger("llmos.worker")


class WorkerLoop:
    """
    Background thread that processes tasks from the queue.

    Flow per task (dynamic planning):
      PENDING → PLANNING → RUNNING
        → loop:
            ask planner for next step (with execution history)
            if planner says done → SUCCESS
            policy check:
              BLOCKED → FAILED immediately
              RISKY   → AWAITING_APPROVAL (blocks on threading.Event)
                APPROVED  → execute
                REJECTED  → CANCELLED
            execute step
            if exit != 0:
              retry up to step_retry_limit times (re-plan with error context)
              if still failing → FAILED (remaining steps SKIPPED)
            append result to history
            loop
        → SUCCESS when planner returns done=True or max_steps reached
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
        max_steps_per_task: int = 20,
        step_retry_limit: int = 2,
    ):
        self.session_factory = session_factory
        self.executor = executor
        self.planner = planner
        self.policy_engine = policy_engine
        self.task_queue = task_queue
        self.approval_events = approval_events
        self.approval_timeout = approval_timeout_seconds
        self.max_steps_per_task = max_steps_per_task
        self.step_retry_limit = step_retry_limit

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

    def _now(self):
        return datetime.datetime.utcnow()

    def _process_task(self, task_id: str):
        with self.session_factory() as session:

            # ── 1. Validate task is PENDING ───────────────────────────────────
            task = session.get(TaskRecord, task_id)
            if task is None:
                logger.error(f"Task {task_id} not found in DB")
                return
            if task.state != TaskState.PENDING:
                logger.warning(f"Task {task_id} is {task.state}, expected PENDING — skipping")
                return

            intent = task.intent

            # ── 2. PENDING → PLANNING ─────────────────────────────────────────
            task.state = TaskState.PLANNING
            task.updated_at = self._now()
            session.commit()
            logger.info(f"Task {task_id}: PLANNING")

            # ── 3. Snapshot workspace context ─────────────────────────────────
            workspace_context = {
                "files": self.executor.list_workspace(),
                "platform": "macOS",
                "shell": "zsh",
            }
            logger.info(
                f"Task {task_id}: workspace has {len(workspace_context['files'])} file(s)"
            )

            # ── 4. PLANNING → RUNNING ─────────────────────────────────────────
            task.state = TaskState.RUNNING
            task.updated_at = self._now()
            session.commit()
            logger.info(f"Task {task_id}: RUNNING")

            # ── 5. Dynamic plan → execute loop ────────────────────────────────
            history: List[dict] = []
            step_number = 0

            while step_number < self.max_steps_per_task:

                # Ask planner for next step
                try:
                    response = self.planner.plan_next(intent, history, workspace_context)
                except RuntimeError as e:
                    task.state = TaskState.FAILED
                    task.error_msg = f"Planner error: {e}"
                    task.updated_at = self._now()
                    session.commit()
                    logger.error(f"Task {task_id}: planner failed — {e}")
                    return

                # Planner signals task is complete
                if response.done:
                    task.state = TaskState.SUCCESS
                    task.updated_at = self._now()
                    session.commit()
                    logger.info(f"Task {task_id}: SUCCESS (planner declared done after {step_number} step(s))")
                    return

                step_number += 1
                command = response.command
                description = response.description
                order = response.order

                logger.info(f"Task {task_id} step {order}: {description!r} — $ {command}")

                # ── Policy check ───────────────────────────────────────────────
                verdict = self.policy_engine.evaluate(command)
                final_command = verdict.transformed_command or command

                if verdict.risk_level == RiskLevel.BLOCKED:
                    task.state = TaskState.FAILED
                    task.error_msg = f"BLOCKED: '{command}' — {verdict.reason}"
                    task.updated_at = self._now()
                    session.commit()
                    logger.warning(f"Task {task_id}: BLOCKED at step {order}")
                    return

                # ── Persist step to DB ─────────────────────────────────────────
                step = StepRecord(
                    task_id=task_id,
                    order=order,
                    description=description,
                    command=final_command,
                    risk_level=verdict.risk_level,
                    requires_approval=(verdict.risk_level == RiskLevel.RISKY),
                    approval_reason=verdict.reason,
                )
                session.add(step)
                session.commit()

                # ── Approval gate (RISKY steps) ────────────────────────────────
                if step.requires_approval:
                    task.state = TaskState.AWAITING_APPROVAL
                    task.updated_at = self._now()
                    session.commit()
                    logger.info(f"Task {task_id}: AWAITING_APPROVAL for step {order}")

                    event = threading.Event()
                    self.approval_events[task_id] = event

                    granted = event.wait(timeout=self.approval_timeout)
                    self.approval_events.pop(task_id, None)

                    if not granted:
                        task.state = TaskState.FAILED
                        task.error_msg = f"Approval timeout for step {order}"
                        task.updated_at = self._now()
                        session.commit()
                        return

                    session.refresh(step)
                    session.refresh(task)

                    if step.approval_decision == "REJECTED":
                        task.state = TaskState.CANCELLED
                        task.updated_at = self._now()
                        session.commit()
                        logger.info(f"Task {task_id}: CANCELLED (step {order} rejected)")
                        return

                    if task.state == TaskState.CANCELLED:
                        return

                    task.state = TaskState.RUNNING
                    task.updated_at = self._now()
                    session.commit()

                # ── Execute step (with per-step retry) ────────────────────────
                step.state = "RUNNING"
                step.started_at = self._now()
                session.commit()

                result = self._execute_with_retry(
                    session, task, step, intent, history, order
                )

                if result is None:
                    # _execute_with_retry already marked task as FAILED
                    return

                # ── Record success and append to history ───────────────────────
                step.stdout = result.stdout
                step.stderr = result.stderr
                step.exit_code = result.exit_code
                step.started_at = result.started_at
                step.finished_at = result.finished_at
                step.state = "SUCCESS"
                session.commit()

                history.append({
                    "order":       order,
                    "description": description,
                    "command":     step.command,
                    "stdout":      result.stdout,
                    "stderr":      result.stderr,
                    "exit_code":   result.exit_code,
                })

                logger.info(f"Task {task_id} step {order}: SUCCESS (exit={result.exit_code})")

                # Refresh workspace context after each step (files may have been created)
                workspace_context["files"] = self.executor.list_workspace()

            # ── Safety cap reached ────────────────────────────────────────────
            task.state = TaskState.FAILED
            task.error_msg = f"Exceeded max_steps_per_task ({self.max_steps_per_task})"
            task.updated_at = self._now()
            session.commit()
            logger.warning(f"Task {task_id}: FAILED (max steps exceeded)")

    def _execute_with_retry(self, session, task, step, intent, history, order):
        """
        Execute a step command. On failure, ask the planner to fix it and retry
        up to self.step_retry_limit times.

        Returns ExecutionResult on success, or None after marking task FAILED.
        """
        current_command = step.command
        current_step_order = order

        for attempt in range(self.step_retry_limit + 1):
            result = self.executor.run(current_command)

            if not result.timed_out and result.exit_code == 0:
                return result

            # Step failed
            failure_reason = (
                f"timeout" if result.timed_out
                else f"exit {result.exit_code}"
            )
            logger.warning(
                f"Task {task.id} step {order} attempt {attempt + 1}: "
                f"FAILED ({failure_reason})"
            )

            if attempt < self.step_retry_limit:
                # Ask LLM to fix the command
                logger.info(
                    f"Task {task.id} step {order}: asking planner to fix "
                    f"(attempt {attempt + 1}/{self.step_retry_limit})"
                )
                try:
                    fix_response = self.planner.fix_step(
                        intent=intent,
                        history=history,
                        failed_command=current_command,
                        stderr=result.stderr,
                        step_order=current_step_order,
                    )
                    new_command = fix_response.command
                    if new_command and new_command != current_command:
                        logger.info(
                            f"Task {task.id} step {order}: retrying with fixed command: "
                            f"$ {new_command}"
                        )
                        # Update the step's command in DB to show the retry
                        step.command = new_command
                        step.stderr = result.stderr
                        step.exit_code = result.exit_code
                        session.commit()
                        current_command = new_command
                        continue
                    else:
                        logger.info(
                            f"Task {task.id} step {order}: planner returned same command, "
                            f"no point retrying"
                        )
                except RuntimeError as e:
                    logger.warning(f"Task {task.id} step {order}: fix_step failed — {e}")

                # Fall through to failure if fix_step errored or returned same command
                break

        # All retries exhausted
        step.stdout = result.stdout
        step.stderr = result.stderr
        step.exit_code = result.exit_code
        step.started_at = result.started_at
        step.finished_at = result.finished_at
        step.state = "FAILED"

        task.state = TaskState.FAILED
        task.error_msg = (
            f"Step {order} failed"
            + (f" (timeout)" if result.timed_out else f" (exit {result.exit_code})")
        )
        task.updated_at = self._now()
        session.commit()

        logger.warning(f"Task {task.id}: FAILED at step {order} after retries")
        return None
