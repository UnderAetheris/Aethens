"""Execution runner: routes an ordinary MultiStepPlan through the existing spine.

The orchestrator NEVER executes a tool itself. It hands an ordinary plan to a
`SpineRunner`, which runs it through the **existing** ExecutiveController ->
Controller -> SafetyLayer -> tool path, one step at a time. Every guarantee
about gated execution is inherited untouched, because no new execution path is
created here.

`ExecSpy` is testing scaffolding (only constructed when `exec_spy=True`) that
proves two structural properties: exactly one plan runs at a time, and every
step was gated by the SafetyLayer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..controller.queue import TaskState

if TYPE_CHECKING:
    from ..controller.controller import Controller
    from ..controller.executive import ExecutiveController
    from ..memory.store import MemoryStore
    from ..planner.plan import MultiStepPlan


_TERMINAL = frozenset({
    TaskState.DONE,
    TaskState.FAILED,
    TaskState.BLOCKED,
    TaskState.WAITING_FOR_CONTEXT,
})


@dataclass
class PlanRunResult:
    """Outcome of running one ordinary MultiStepPlan through the existing spine."""

    failed: bool
    blocked: bool
    output: str
    plan_id: str | None = None    # task id the plan was saved under (for rollback)
    repairs_via: str = "none"     # "reflection" (Reflection owned the repair) | "none"


class SpineRunner:
    """Runs an ordinary MultiStepPlan via the existing ExecutiveController.

    No tool, no SafetyLayer, no writer is held here — only the existing
    Executive, which owns all of those. Concurrency is always 1: this is called
    once per subgoal, in order, by the orchestrator's deterministic loop.
    """

    def __init__(self, executive: "ExecutiveController") -> None:
        self._executive = executive

    def run(self, plan: "MultiStepPlan", description: str) -> PlanRunResult:
        queue = self._executive._queue
        memory = self._executive._memory
        rec = queue.enqueue(description)
        # Re-key the plan to the queue-assigned task id so the Executive reuses
        # the exact plan the orchestrator built (skill match already applied).
        plan.task_id = rec.id
        self._executive._plan_store.save(plan)

        start = len(memory.history())
        # Hard cap on ticks so a pathological repair/retry loop can never hang
        # the single-threaded scheduler. Bounded, deterministic, no hidden exec.
        max_ticks = 64
        ticks = 0
        while ticks < max_ticks:
            cur = queue.get(rec.id)
            if cur is None or cur.state in _TERMINAL:
                break
            self._executive.run_once()
            ticks += 1

        cur = queue.get(rec.id)
        terminal = cur.state if cur is not None else TaskState.FAILED
        events = memory.history()[start:]
        repairs = any(e.get("kind") == "repair_inserted" for e in events)

        failed = terminal in (TaskState.FAILED, TaskState.BLOCKED, TaskState.WAITING_FOR_CONTEXT)
        blocked = terminal in (TaskState.BLOCKED, TaskState.WAITING_FOR_CONTEXT)
        return PlanRunResult(
            failed=failed,
            blocked=blocked,
            output=cur.detail if cur is not None else "",
            plan_id=rec.id,
            repairs_via="reflection" if repairs else "none",
        )


class ExecSpy:
    """Testing scaffold: proves one-plan-at-a-time + every step gated.

    Only attached when an orchestrator is built with `exec_spy=True`. Wraps the
    Executive's Controller.handle_step to count live concurrency and to confirm
    every step was routed through the SafetyLayer (no hidden execution).
    """

    def __init__(self, controller: "Controller", memory: "MemoryStore") -> None:
        self._controller = controller
        # SafetyLayer logs to the Controller's own memory; read that to prove
        # every step was gated (the executive's memory is a different store).
        self._memory = getattr(controller, "memory", memory)
        self.max_concurrent = 0
        self._inflight = 0
        self.steps = 0
        self._all_gated = True
        self._orig = controller.handle_step
        controller.handle_step = self._wrap  # type: ignore[assignment]

    def _wrap(self, tool: str, arg: str, **kw: Any):  # type: ignore[no-untyped-def]
        self._inflight += 1
        self.max_concurrent = max(self.max_concurrent, self._inflight)
        before = len(self._memory.history())
        try:
            result = self._orig(tool, arg, **kw)
        finally:
            self._inflight -= 1
        after = self._memory.history()
        gated = any(
            e.get("kind") in ("action_allowed", "action_blocked", "action_preview")
            for e in after[before:]
        )
        self.steps += 1
        self._all_gated = self._all_gated and gated
        return result

    @property
    def all_ran_through_safetylayer(self) -> bool:
        return (
            self.steps > 0
            and getattr(self._controller, "safety", None) is not None
            and self._all_gated
        )
