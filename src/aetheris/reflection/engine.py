from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..planner.plan import MultiStepPlan

# Reflection's own retry ceiling — the executive's _MAX_RETRIES is the hard cap;
# this constant lets reflection signal RETRY_STEP vs ABORT independently.
_MAX_REFLECT_RETRIES = 3


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
    its verdict through the unchanged Controller -> SafetyLayer -> Tool path.
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
    failure_kind: str = ""   # FailureKind string value from deterministic parser, or "" if unclassified


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
        pick -> run -> record -> reflect(outcome) -> act -> advance
    """

    def __init__(
        self,
        registry_tools: tuple[str, ...] = (),
        max_repair_steps: int = 3,
        understanding: Any = None,
        reasoning: Any = None,
        model_patcher: Any = None,
    ) -> None:
        self._tools = frozenset(registry_tools)
        self._max_repair = max_repair_steps
        self._understanding = understanding
        self._reasoning = reasoning
        self._model_patcher = model_patcher

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def reflect(self, outcome: StepOutcome, plan: MultiStepPlan) -> ReflectionResult:
        """Return a verdict given what just happened.

        Rules (in priority order):
        1. Safety block → never retry → REQUEST_CONTEXT (or ABORT if no repair).
        2. FailureKind (deterministic classification) → rule-based verdict.
        3. Success → CONTINUE.
        4. Repair suggestions present and valid → INSERT_REPAIR_STEPS.
        5. Transient failure within retry budget → RETRY_STEP.
        6. Transient failure, retries exhausted → ABORT.
        """
        if outcome.blocked:
            # Safety block is a deliberate "no" — never loop at the wall.
            return ReflectionResult(
                verdict=Verdict.REQUEST_CONTEXT,
                reason=f"safety blocked step {outcome.step_index}: {outcome.output}",
            )

        # Deterministic failure classification keys off existing verdicts.
        fk = outcome.failure_kind
        if fk == "unsafe_blocked":
            return ReflectionResult(
                verdict=Verdict.REQUEST_CONTEXT,
                reason=f"unsafe_blocked on step {outcome.step_index}: never blind-retry the wall",
            )
        if fk == "command_not_found":
            return ReflectionResult(
                verdict=Verdict.REQUEST_CONTEXT,
                reason=f"command_not_found on step {outcome.step_index}: environment issue, pause",
            )
        if fk in ("missing_import", "syntax_error", "assertion_failure"):
            return self._code_failure_repair(outcome, plan, fk)

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
    # Repair construction (with optional Understanding enrichment)       #
    # ------------------------------------------------------------------ #

    def _build_import_repair(self, outcome: StepOutcome) -> list[tuple[str, str]]:
        """Build a concrete edit_file repair for a missing import.

        Queries the Understanding model (if available) to find the correct
        module that exports the missing symbol.  Falls back to an empty
        list if the model has no answer, letting the executive use v0
        deterministic behavior.
        """
        output_lower = outcome.output.lower()
        symbol_name = None
        for marker in ("no module named ", "importerror: "):
            idx = output_lower.find(marker)
            if idx != -1:
                rest = outcome.output[idx + len(marker):].strip()
                symbol_name = rest.split()[0].strip("'\"") if rest else None
                break
        if symbol_name is None:
            return []
        if self._understanding is None:
            return []
        module = self._understanding.exporting_module(symbol_name)
        if module is None:
            return []
        arg = json.dumps({
            "path": "",
            "find": "\n",
            "replace": f"\nfrom {module} import {symbol_name}\n",
        })
        return [("edit_file", arg)]

    def _code_failure_repair(
        self, outcome: StepOutcome, plan: MultiStepPlan, failure_kind: str
    ) -> ReflectionResult:
        """Insert a repair for a code failure.

        Tries a model-assisted patch first (validated in a sandbox, handed back
        as candidate content).  If the model is off or its patch fails any gate,
        falls back to the deterministic repair.  Reflection owns the verdict in
        both cases; the edit always executes through the unchanged writer.
        """
        steps: list[tuple[str, str]] | None = None
        reason = ""
        if self._model_patcher is not None:
            proposal = self._model_patcher.propose_repair(outcome, plan)
            if proposal is not None:
                steps = list(proposal.repair_steps)
                reason = (
                    f"model-assisted patch validated in sandbox "
                    f"(resembles_retired={proposal.resembles_retired})"
                )
        if steps is None:
            steps = self._build_import_repair(outcome) if failure_kind == "missing_import" else []
            reason = f"{failure_kind} on step {outcome.step_index}: insert deterministic repair"

        if self._reasoning is not None:
            try:
                deliberation = self._reasoning.deliberate_for_repair(outcome)
                self._reasoning._journal_append(deliberation)
            except Exception:
                pass
        return ReflectionResult(
            verdict=Verdict.INSERT_REPAIR_STEPS,
            reason=reason,
            repair_steps=steps,
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
