from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config, PromotionConfig
from ..learning.plan_review import PlanReviewQueue, ReviewStatus
from ..memory.lessons import ExperienceMemory, OutcomeType
from ..memory.store import MemoryStore
from ..planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from ..reasoning.engine import ReasoningEngine
from ..reflection.engine import ReflectionEngine, StepOutcome, Verdict
from ..reflection.failure_parser import FailureParser
from ..understanding.engine import RepoUnderstanding
from .controller import Controller
from .queue import TaskQueue, TaskState

# How many consecutive idle ticks must pass before the improvement loop runs.
_IDLE_TICKS_BEFORE_IMPROVE = 3

# Maximum times a step is re-planned before the whole task is failed.
_MAX_RETRIES = 2

# Minimum complexity (number of steps) to trigger plan review.
_PLAN_REVIEW_STEP_THRESHOLD = 1


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
    - Each step is handed to the unchanged Controller -> SafetyLayer -> Tool path.
    - Multi-step plans are executed step-by-step; progress is persisted so
      partial execution survives restarts.
    - On step fail/block, re-plan the remainder up to max_retries times;
      exhausted -> task FAILED.
    - When the queue is empty for idle_ticks_before_improve consecutive ticks,
      run idle actions: (a) eval + keyword-learning, (c) optional skill promotion.
    - Plans with more than _PLAN_REVIEW_STEP_THRESHOLD steps are submitted
      for user review before execution (when plan_review is provided).
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
        reflection: ReflectionEngine | None = None,
        plan_review: PlanReviewQueue | None = None,
        skill_promotion=None,  # IdleSkillPromotion | None — default off
        promotion_budget: int = 1,
        promotion_config: PromotionConfig | None = None,
        understanding: RepoUnderstanding | None = None,
        reasoning: ReasoningEngine | None = None,
        experience: ExperienceMemory | None = None,
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
        self._plan_store = plan_store or PlanStore(config.log_path.replace(".jsonl", "_plans"))
        if reflection is not None:
            self._reflection: ReflectionEngine | None = reflection
        elif config.reflection_enabled:
            self._reflection = ReflectionEngine(understanding=understanding, reasoning=reasoning)
        else:
            self._reflection = None
        self._plan_review = plan_review
        self._skill_promotion = skill_promotion
        self._promotion_budget = promotion_budget
        self._promotion_config = promotion_config
        self._failure_parser = FailureParser()
        self._understanding = understanding
        self._reasoning = reasoning
        self._experience = experience

    def run_once(self) -> Tick:
        nxt = self._queue.next_queued()
        if nxt is None:
            return self._on_idle()
        self._idle_ticks = 0
        tick = self._run_task(nxt.id)
        # Experience write path: a pure side-effect.  It observes what happened
        # and records a Lesson; it adds no step, gate, or decision, so it is
        # safe to keep on.  It never reads back here (consumption is gated).
        self._observe_experience(tick)
        return tick

    @staticmethod
    def _outcome_for_tick(tick: Tick) -> OutcomeType | None:
        """Map a terminal Tick to a provenance OutcomeType (or None if non-terminal)."""
        o = tick.outcome
        if o in ("done", "step_done"):
            return OutcomeType.WORKED_WELL
        if o in ("blocked", "waiting_for_context"):
            return OutcomeType.FAILED_SAFELY
        if o == "failed":
            return OutcomeType.FAILED_REPEATEDLY
        return None

    def _observe_experience(self, tick: Tick) -> None:
        if self._experience is None or tick.task_id is None:
            return
        outcome = self._outcome_for_tick(tick)
        if outcome is None:
            return
        self._experience.record(
            outcome=outcome,
            problem=f"task {tick.task_id} ended '{tick.outcome}'",
            cause=tick.outcome or "unknown",
            fix="(recorded for later mining; advisory, no action taken)",
            related_task=tick.task_id,
        )

    # ------------------------------------------------------------------ #
    # Task execution                                                       #
    # ------------------------------------------------------------------ #

    def _run_task(self, task_id: str) -> Tick:
        rec = self._queue.transition(task_id, TaskState.PLANNING, "executive picked up")
        rec = self._queue.transition(task_id, TaskState.EXECUTING, "handed to controller")

        # Load or create the multi-step plan for this task.
        plan = self._plan_store.load(task_id)
        if plan is None:
            plan = self._controller.planner.plan_multi(rec.task, task_id)
            self._plan_store.save(plan)
            rec.plan_source = plan.plan_source
            self._queue._store.append(rec.to_dict())
            self._memory.record(
                "plan_created",
                {"task_id": task_id, "steps": len(plan.steps), "task": rec.task, "plan_source": plan.plan_source},
            )

        # If plan review is enabled and plan is complex, submit for review.
        if (
            self._plan_review is not None
            and len(plan.steps) > _PLAN_REVIEW_STEP_THRESHOLD
            and not plan.source.startswith("skill:")
        ):
            pending = self._plan_review.submit(rec.task, plan)
            self._queue.transition(
                task_id, TaskState.WAITING_FOR_CONTEXT,
                f"pending review: {pending.review_id}",
            )
            self._memory.record(
                "plan_review_submitted",
                {"task_id": task_id, "review_id": pending.review_id, "steps": len(plan.steps)},
            )
            return Tick(did_work=True, task_id=task_id, outcome="plan_review")

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
        step_index = plan.steps.index(step)
        attempt = self._retry_counts.get(task_id, 0) + 1

        try:
            result = self._controller.handle_step(step.tool, step.arg)
        except Exception as exc:
            if self._reflection is None:
                return self._handle_step_failure(task_id, plan, step, f"exception: {exc!r}")
            failure_kind = self._failure_parser.classify(f"exception: {exc!r}", False)
            outcome = StepOutcome(
                task_id=task_id, step_index=step_index, tool=step.tool, arg=step.arg,
                ok=False, output=f"exception: {exc!r}", blocked=False, attempt=attempt,
                failure_kind=failure_kind.value,
            )
            return self._apply_verdict(task_id, plan, step, outcome)

        blocked = result.output.startswith("blocked:")

        if not result.ok:
            if self._reflection is None:
                # Legacy path: safety block -> BLOCKED, transient failure -> retry.
                if blocked:
                    step.status = StepStatus.BLOCKED
                    self._plan_store.save(plan)
                    self._retry_counts.pop(task_id, None)
                    self._queue.transition(task_id, TaskState.BLOCKED, result.output)
                    return Tick(did_work=True, task_id=task_id, outcome="blocked")
                return self._handle_step_failure(task_id, plan, step, result.output)
            failure_kind = self._failure_parser.classify(result.output, blocked)
            outcome = StepOutcome(
                task_id=task_id, step_index=step_index, tool=step.tool, arg=step.arg,
                ok=result.ok, output=result.output, blocked=blocked, attempt=attempt,
                failure_kind=failure_kind.value,
            )
            return self._apply_verdict(task_id, plan, step, outcome)

        # Step succeeded.
        if self._reflection is not None:
            outcome = StepOutcome(
                task_id=task_id, step_index=step_index, tool=step.tool, arg=step.arg,
                ok=True, output=result.output, blocked=False, attempt=attempt,
            )
            reflection = self._reflection.reflect(outcome, plan)
            self._memory.record(
                "reflection_decision",
                {"task_id": task_id, "step": step_index, "verdict": reflection.verdict.value,
                 "reason": reflection.reason},
            )

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

        self._queue.transition(task_id, TaskState.QUEUED, "step done, continuing")
        return Tick(did_work=True, task_id=task_id, outcome="step_done")

    def _apply_verdict(
        self, task_id: str, plan: MultiStepPlan, step: PlanStep, outcome: StepOutcome
    ) -> Tick:
        """Ask reflection for a verdict and enact it using existing executive mechanisms."""
        reflection = self._reflection.reflect(outcome, plan)
        step_index = outcome.step_index
        self._memory.record(
            "reflection_decision",
            {"task_id": task_id, "step": step_index, "verdict": reflection.verdict.value,
             "reason": reflection.reason},
        )

        if reflection.verdict == Verdict.CONTINUE:
            # Shouldn't reach here on a failure path, but handle gracefully.
            return Tick(did_work=True, task_id=task_id, outcome="step_done")

        if reflection.verdict == Verdict.RETRY_STEP:
            return self._handle_step_failure(task_id, plan, step, outcome.output)

        if reflection.verdict == Verdict.REQUEST_CONTEXT:
            step.status = StepStatus.BLOCKED
            self._plan_store.save(plan)
            self._retry_counts.pop(task_id, None)
            self._queue.transition(task_id, TaskState.WAITING_FOR_CONTEXT, outcome.output)
            return Tick(did_work=True, task_id=task_id, outcome="waiting_for_context")

        if reflection.verdict == Verdict.INSERT_REPAIR_STEPS:
            inserted = plan.insert_repair_after(step_index, reflection.repair_steps)
            if inserted:
                # Reset the original step to PENDING so it retries after repairs complete.
                # Repairs were inserted at step_index+1 .. step_index+n_repairs;
                # original step stays at step_index and must wait for the last repair.
                n_repairs = len(reflection.repair_steps)
                step.status = StepStatus.PENDING
                step.depends_on = [step_index + n_repairs]
                self._plan_store.save(plan)
                self._memory.record(
                    "repair_inserted",
                    {"task_id": task_id, "after_step": step_index,
                     "repairs": reflection.repair_steps},
                )
                self._queue.transition(task_id, TaskState.QUEUED, "repair steps inserted")
                return Tick(did_work=True, task_id=task_id, outcome="repair_inserted")
            # insert failed validation — fall through to abort

        # ABORT (or fallback from failed insert)
        step.status = StepStatus.FAILED
        self._plan_store.save(plan)
        self._retry_counts.pop(task_id, None)
        self._queue.transition(task_id, TaskState.FAILED, f"reflection abort: {reflection.reason}")
        return Tick(did_work=True, task_id=task_id, outcome="failed")

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

        # (c) Idle skill promotion: bounded, cooperative, only when provably idle.
        if self._skill_promotion is not None:
            self._run_idle_promotion()

        return Tick(did_work=False, improved=improved)

    def _run_idle_promotion(self) -> None:
        self._memory.record("idle_promotion_started", {"budget": self._promotion_budget})
        tried = 0
        for candidate in self._skill_promotion.mine():
            if tried >= self._promotion_budget:
                break
            if self._queue.next_queued() is not None:
                self._memory.record("idle_promotion_yielded", {"reason": "work arrived"})
                return
            self._skill_promotion.try_one(candidate)
            tried += 1

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
