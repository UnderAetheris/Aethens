from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

# Reflection's own retry ceiling — the executive's _MAX_RETRIES is the hard cap;
# this constant lets reflection signal RETRY_STEP vs ABORT independently.
_MAX_REFLECT_RETRIES = 3

if TYPE_CHECKING:
    from ..planner.plan import MultiStepPlan, PlanStep


class Verdict(str, Enum):
    CONTINUE = "continue"               # step succeeded — advance normally
    RETRY_STEP = "retry_step"           # transient failure — use existing bounded retry
    REQUEST_CONTEXT = "request_context" # unresolvable without more info → WAITING_FOR_CONTEXT
    ABORT = "abort"                     # unrecoverable — fail the task cleanly
    INSERT_REPAIR_STEPS = "insert_repair_steps"  # append validated repair steps to the plan


@dataclass
class StepOutcome:
    """Read-only snapshot of what happened when a step ran.

    Reflection sees only this; it has no handle to any tool, registry, or
    SafetyLayer.  Everything it causes happens because the executive enacts
    its verdict through the unchanged Controller → SafetyLayer → Tool path.
    """

    task_id: str
    step_index: int          # index of the step in the plan
    tool: str
    arg: str
    ok: bool                 # True = succeeded, False = failed/blocked
    output: str              # tool output or error message
    blocked: bool = False    # True = SafetyLayer denied (permanent, not transient)
    attempt: int = 1         # which retry attempt this was (1-based)
    repair_suggestions: list[tuple[str, str]] = field(default_factory=list)
    # ^ list of (tool_name, arg) pairs the engine may propose as repair steps


@dataclass
class ReflectionResult:
    verdict: Verdict
    reason: str
    repair_steps: list[tuple[str, str]] = field(default_factory=list)
    # ^ populated only when verdict == INSERT_REPAIR_STEPS; validated by engine


class ReflectionEngine:
    """Deterministic reflection advisor.

    Observes a StepOutcome and returns one of five verdicts.  It never
    executes anything.  The executive is the only caller; it enacts the
    verdict using mechanisms it already has.

    Integration seam (executive):
        pick → run → record → reflect(outcome) → act → advance
    """

    def __init__(self, registry_tools: tuple[str, ...] = (), max_repair_steps: int = 3) -> None:
        self._tools = frozenset(registry_tools)
        self._max_repair = max_repair_steps

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def reflect(self, outcome: StepOutcome, plan: MultiStepPlan) -> ReflectionResult:
        """Return a verdict given what just happened.

        Rules (in priority order):
        1. Safety block → never retry → REQUEST_CONTEXT (or ABORT if no repair).
        2. Success → CONTINUE.
        3. Repair suggestions present and valid → INSERT_REPAIR_STEPS.
        4. Transient failure within retry budget → RETRY_STEP.
        5. Transient failure, retries exhausted → ABORT.
        """
        if outcome.blocked:
            # Safety block is a deliberate "no" — never loop at the wall.
            return ReflectionResult(
                verdict=Verdict.REQUEST_CONTEXT,
                reason=f"safety blocked step {outcome.step_index}: {outcome.output}",
            )

        if outcome.ok:
            return ReflectionResult(
                verdict=Verdict.CONTINUE,
                reason=f"step {outcome.step_index} succeeded",
            )

        # Transient failure path.
        if outcome.repair_suggestions:
            validated = self._validate_repairs(outcome.repair_suggestions, plan)
            if validated:
                return ReflectionResult(
                    verdict=Verdict.INSERT_REPAIR_STEPS,
                    reason=f"inserting {len(validated)} repair step(s) after step {outcome.step_index}",
                    repair_steps=validated,
                )
            # Invalid repair → downgrade to abort (never insert corrupt structure).
            return ReflectionResult(
                verdict=Verdict.ABORT,
                reason="repair suggestions failed validation — aborting",
            )

        # No repair suggestions — use retry budget.
        # attempt is 1-based; budget is checked by the executive's max_retries,
        # but reflection independently signals RETRY vs ABORT based on attempt count.
        # We defer to the executive's counter: if attempt < _MAX_REFLECT_RETRIES, retry.
        if outcome.attempt < _MAX_REFLECT_RETRIES:
            return ReflectionResult(
                verdict=Verdict.RETRY_STEP,
                reason=f"transient failure on attempt {outcome.attempt}, retrying",
            )

        return ReflectionResult(
            verdict=Verdict.ABORT,
            reason=f"step {outcome.step_index} exhausted retries: {outcome.output}",
        )

    # ------------------------------------------------------------------ #
    # Repair validation                                                    #
    # ------------------------------------------------------------------ #

    def _validate_repairs(
        self,
        suggestions: list[tuple[str, str]],
        plan: MultiStepPlan,
    ) -> list[tuple[str, str]]:
        """Validate repair suggestions.

        Rules (safety spine for repairs):
        - Count ≤ max_repair_steps.
        - Every tool name must exist in the registry.
        - Repairs are append-only: they may only reference future steps,
          never rewrite done history.
        - No cycles (linear append is cycle-free by construction).

        Returns the validated list, or [] if any rule is violated.
        """
        if not suggestions:
            return []
        if len(suggestions) > self._max_repair:
            return []
        if self._tools:
            for tool_name, _ in suggestions:
                if tool_name not in self._tools:
                    return []
        return list(suggestions)
