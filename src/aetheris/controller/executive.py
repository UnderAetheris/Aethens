from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..memory.store import MemoryStore
from ..planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from .controller import Controller
from .queue import TaskQueue, TaskState

# How many consecutive idle ticks must pass before the improvement loop runs.
_IDLE_TICKS_BEFORE_IMPROVE = 3

# Maximum times a step is re-planned before the whole task is failed.
_MAX_RETRIES = 2


@dataclass
class Tick:
    did_work: bool
    task_id: str | None = None
    outcome: str | None = None
    improved: bool | None = None


class ExecutiveController:
    """Orchestrates live work and idle-time improvement without bypassing safety.

    Policy:
    - While tasks are queued, drain them one step at a time.
    - Each step is handed to the unchanged Controller → SafetyLayer → Tool path.
    - Multi-step plans are executed step-by-step; progress is persisted so
      partial execution survives restarts.
    - On step fail/block, re-plan the remainder up to max_retries times;
      exhausted → task FAILED.
    - When the queue is empty for idle_ticks_before_improve consecutive ticks,
      run one improvement attempt (eval + learn), then reset the idle counter.
    """

    def __init__(
        self,
        config: Config,
        queue: TaskQueue,
        memory: MemoryStore,
        controller: Controller | None = None,
        improve_fn=None,
        idle_ticks_before_improve: int = _IDLE_TICKS_BEFORE_IMPROVE,
        max_retries: int = _MAX_RETRIES,
        plan_store: PlanStore | None = None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._memory = memory
        self._controller = controller or Controller(config)
        self._improve_fn = improve_fn
        self._idle_threshold = idle_ticks_before_improve
        self._max_retries = max_retries
        self._idle_ticks: int = 0
        self._retry_counts: dict[str, int] = {}
        # PlanStore lives next to the queue journal by default.
        self._plan_store = plan_store or PlanStore(config.log_path.replace(".jsonl", "_plans"))

    def run_once(self) -> Tick:
        nxt = self._queue.next_queued()
        if nxt is None:
            return self._on_idle()
        self._idle_ticks = 0
        return self._run_task(nxt.id)

    # ------------------------------------------------------------------ #
    # Task execution                                                       #
    # ------------------------------------------------------------------ #

    def _run_task(self, task_id: str) -> Tick:
        rec = self._queue.transition(task_id, TaskState.PLANNING, "executive picked up")
        self._queue.transition(task_id, TaskState.EXECUTING, "handed to controller")

        # Load or create the multi-step plan for this task.
        plan = self._plan_store.load(task_id)
        if plan is None:
            plan = self._controller.planner.plan_multi(rec.task, task_id)
            self._plan_store.save(plan)
            self._memory.record(
                "plan_created",
                {"task_id": task_id, "steps": len(plan.steps), "task": rec.task},
            )

        # Execute the next ready step.
        step = plan.next_ready()
        if step is None:
            # All steps done or no step is unblocked — shouldn't happen normally.
            if plan.is_complete():
                self._plan_store.delete(task_id)
                self._queue.transition(task_id, TaskState.DONE, "all steps complete")
                return Tick(did_work=True, task_id=task_id, outcome="done")
            self._queue.transition(task_id, TaskState.FAILED, "no ready step")
            return Tick(did_work=True, task_id=task_id, outcome="failed")

        return self._execute_step(task_id, plan, step)

    def _execute_step(self, task_id: str, plan: MultiStepPlan, step: PlanStep) -> Tick:
        try:
            result = self._controller.handle_step(step.tool, step.arg)
        except Exception as exc:
            return self._handle_step_failure(
                task_id, plan, step, f"exception: {exc!r}"
            )

        if not result.ok:
            # A safety block is permanent — don't retry, go straight to BLOCKED.
            if result.output.startswith("blocked:"):
                step.status = StepStatus.BLOCKED
                self._plan_store.save(plan)
                self._retry_counts.pop(task_id, None)
                self._queue.transition(task_id, TaskState.BLOCKED, result.output)
                return Tick(did_work=True, task_id=task_id, outcome="blocked")
            return self._handle_step_failure(task_id, plan, step, result.output)

        # Step succeeded — mark done, persist, check if whole plan is complete.
        step.status = StepStatus.DONE
        step.output = result.output
        self._plan_store.save(plan)
        self._memory.record(
            "step_done",
            {"task_id": task_id, "tool": step.tool, "output": result.output},
        )
        self._retry_counts.pop(task_id, None)

        if plan.is_complete():
            self._plan_store.delete(task_id)
            outputs = " | ".join(s.output for s in plan.steps if s.output)
            self._queue.transition(task_id, TaskState.DONE, outputs)
            return Tick(did_work=True, task_id=task_id, outcome="done")

        # More steps remain — re-queue so the next tick picks up the next step.
        self._queue.transition(task_id, TaskState.QUEUED, "step done, continuing")
        return Tick(did_work=True, task_id=task_id, outcome="step_done")

    def _handle_step_failure(
        self, task_id: str, plan: MultiStepPlan, step: PlanStep, reason: str
    ) -> Tick:
        retries = self._retry_counts.get(task_id, 0)
        if retries < self._max_retries:
            # Reset the failed step to PENDING so it can be retried on the next run.
            step.status = StepStatus.PENDING
            self._plan_store.save(plan)
            self._retry_counts[task_id] = retries + 1
            self._memory.record(
                "step_replan",
                {"task_id": task_id, "attempt": retries + 1, "reason": reason},
            )
            self._queue.transition(
                task_id, TaskState.FAILED, f"step failed (attempt {retries + 1}): {reason}"
            )
            self._queue.transition(task_id, TaskState.QUEUED, "retrying remaining steps")
            return Tick(did_work=True, task_id=task_id, outcome="retrying")

        # Retries exhausted — fail the whole task.
        step.status = StepStatus.FAILED
        self._plan_store.save(plan)
        self._retry_counts.pop(task_id, None)
        self._queue.transition(task_id, TaskState.FAILED, f"step exhausted retries: {reason}")
        return Tick(did_work=True, task_id=task_id, outcome="failed")

    # ------------------------------------------------------------------ #
    # Idle / improvement                                                   #
    # ------------------------------------------------------------------ #

    def _on_idle(self) -> Tick:
        self._idle_ticks += 1
        if self._improve_fn is None or self._idle_ticks < self._idle_threshold:
            self._memory.record(
                "executive_idle",
                {
                    "idle_ticks": self._idle_ticks,
                    "threshold": self._idle_threshold,
                    "detail": "no improver configured" if self._improve_fn is None
                              else "waiting for idle threshold",
                },
            )
            return Tick(did_work=False)
        self._idle_ticks = 0
        self._memory.record("executive_improve_start", {})
        improved = bool(self._improve_fn())
        self._memory.record("executive_improve_done", {"improved": improved})
        return Tick(did_work=False, improved=improved)

    def drain(self, max_tasks: int = 100) -> list[Tick]:
        """Process all currently queued tasks (up to max_tasks). Does not trigger improvement."""
        ticks: list[Tick] = []
        while self._queue.next_queued() is not None and len(ticks) < max_tasks:
            ticks.append(self.run_once())
        return ticks

    def trigger_improvement(self) -> Tick:
        """Run one improvement cycle immediately, regardless of idle state."""
        if self._improve_fn is None:
            self._memory.record("executive_improve_skipped", {"reason": "no improver configured"})
            return Tick(did_work=False, improved=False)
        self._idle_ticks = 0
        self._memory.record("executive_improve_start", {"triggered": "manual"})
        improved = bool(self._improve_fn())
        self._memory.record("executive_improve_done", {"improved": improved})
        return Tick(did_work=False, improved=improved)
