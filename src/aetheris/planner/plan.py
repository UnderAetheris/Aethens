from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    WAITING_FOR_CONTEXT = "waiting_for_context"


@dataclass
class PlanStep:
    """One node in a multi-step plan.

    `depends_on` is a list of step indices that must be DONE before this
    step is eligible to run.  An empty list means no dependencies (ready
    as soon as the plan starts).
    """

    tool: str
    arg: str
    reason: str
    status: StepStatus = StepStatus.PENDING
    depends_on: list[int] = field(default_factory=list)
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanStep":
        d = dict(d)
        d["status"] = StepStatus(d["status"])
        return cls(**d)


@dataclass
class MultiStepPlan:
    """A small DAG of PlanSteps for one task.

    A single-step plan is the degenerate case: one step, no dependencies.
    That is how existing single-step behaviour is preserved by construction.
    """

    task_id: str
    steps: list[PlanStep]
    created_at: float = field(default_factory=time.time)
    source: str = ""  # audit: skill id+version, or "" for planner-decomposed
    task: str = ""  # original task text (used for trigger derivation in SkillPromoter)
    plan_source: str = ""  # decision label: skill:name@v1 | decomposed | fallback:reason

    # ------------------------------------------------------------------ #
    # DAG helpers                                                          #
    # ------------------------------------------------------------------ #

    def next_ready(self) -> PlanStep | None:
        """Return the first PENDING step whose dependencies are all DONE."""
        done_indices = {i for i, s in enumerate(self.steps) if s.status == StepStatus.DONE}
        for step in self.steps:
            if step.status == StepStatus.PENDING:
                if all(d in done_indices for d in step.depends_on):
                    return step
        return None

    def is_complete(self) -> bool:
        return all(s.status == StepStatus.DONE for s in self.steps)

    def is_failed(self) -> bool:
        return any(s.status in (StepStatus.FAILED, StepStatus.BLOCKED) for s in self.steps)

    def remaining(self) -> list[PlanStep]:
        """Steps that are still PENDING (not yet done, failed, or blocked)."""
        return [s for s in self.steps if s.status == StepStatus.PENDING]

    def insert_repair_after(self, after_index: int, repairs: list[tuple[str, str]]) -> bool:
        """Append repair steps after `after_index`, then re-queue the original step after them.

        Layout after insertion (after_index=0, 1 repair):
          [0: original(PENDING, depends_on=[1]),  1: repair(PENDING, depends_on=[])]

        Repair steps have no dependency on the original failing step (they run first).
        The original step is left for the caller to update its depends_on to point at
        the last repair index (after_index + n_repairs).

        Append-only, forward-only: never modifies steps at or before after_index.
        Returns False (and makes no change) if repairs is empty.
        """
        if not repairs:
            return False
        insert_at = after_index + 1
        n_new = len(repairs)
        # Shift depends_on for all steps that come after the insertion point.
        for step in self.steps[insert_at:]:
            step.depends_on = [d + n_new if d >= insert_at else d for d in step.depends_on]
        # Build repair steps with no back-dependency on the original failing step.
        new_steps: list[PlanStep] = []
        for i, (tool, arg) in enumerate(repairs):
            # Each repair depends only on the previous repair (linear chain), not on original.
            dep = [insert_at + i - 1] if i > 0 else []
            new_steps.append(PlanStep(tool=tool, arg=arg, reason="repair", depends_on=dep))
        self.steps[insert_at:insert_at] = new_steps
        return True

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "source": self.source,
            "task": self.task,
            "plan_source": self.plan_source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiStepPlan":
        return cls(
            task_id=d["task_id"],
            steps=[PlanStep.from_dict(s) for s in d["steps"]],
            created_at=d.get("created_at", 0.0),
            source=d.get("source", ""),
            task=d.get("task", ""),
            plan_source=d.get("plan_source", ""),
        )


class PlanStore:
    """Persists one MultiStepPlan per task as a JSON sidecar file.

    Path: <journal_dir>/<task_id>.plan.json
    This keeps plans durable across restarts so partial execution can resume.
    """

    def __init__(self, journal_dir: str) -> None:
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self._dir / f"{task_id}.plan.json"

    def save(self, plan: MultiStepPlan) -> None:
        self._path(plan.task_id).write_text(
            json.dumps(plan.to_dict(), indent=2), encoding="utf-8"
        )

    def load(self, task_id: str) -> MultiStepPlan | None:
        p = self._path(task_id)
        if not p.exists():
            return None
        return MultiStepPlan.from_dict(json.loads(p.read_text(encoding="utf-8")))

    def delete(self, task_id: str) -> None:
        p = self._path(task_id)
        if p.exists():
            p.unlink()
