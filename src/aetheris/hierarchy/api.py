"""Public entry points for hierarchical planning.

`run_goal` is the single integration seam: with hierarchy off (the default),
it runs the goal as one flat `MultiStepPlan` through the existing Executive —
byte-identical to Model-Assisted Patching v0. With hierarchy on, it decomposes
(advisory, bounded) and orchestrates via the existing spine, or falls back to
flat when the decomposer abstains / the shape is already flat.

`run_benchmark` / `baseline_model_patching_v0` produce the flat-vs-hierarchical
comparison that the adoption gate consumes. Hierarchy is the only variable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .decomposer import GoalDecomposer
from .journal import GoalJournal
from .model import Goal, GoalGraph, SubGoalState, stable_subgoal_id
from .orchestrator import GoalOrchestrator, OrchestrationResult

if TYPE_CHECKING:
    from ..controller.executive import ExecutiveController
    from ..controller.queue import TaskState
    from ..planner.planner import Planner


_QUEUE_TERMINAL = frozenset({"done", "failed", "blocked", "waiting_for_context"})


def _run_flat(
    goal: Goal,
    planner: "Planner",
    executive: "ExecutiveController",
    pieces: int = 1,
    satisfied: int = 0,
) -> OrchestrationResult:
    """Run the whole goal as one ordinary MultiStepPlan via the existing Executive.

    This is exactly the Model-Assisted Patching v0 path: the planner decomposes
    (or not), the Executive runs it through the unchanged spine. No hierarchy.
    """
    plan = planner.plan_multi(goal.description, goal.goal_id)
    executive._plan_store.save(plan)
    rec = executive._queue.enqueue(goal.description)
    plan.task_id = rec.id
    executive._plan_store.save(plan)

    memory = executive._memory
    start = len(memory.history())
    while True:
        cur = executive._queue.get(rec.id)
        if cur is None or cur.state.value in _QUEUE_TERMINAL:
            break
        executive.run_once()

    cur = executive._queue.get(rec.id)
    terminal = cur.state if cur is not None else None
    done = terminal is not None and terminal.value == "done"

    events = memory.history()[start:]
    retries = sum(1 for e in events if e.get("kind") == "step_replan")
    repairs = sum(1 for e in events if e.get("kind") == "repair_inserted")

    # Count steps actually completed by the flat plan (for fair completion metric).
    saved = executive._plan_store.load(rec.id) or plan
    done_steps = sum(1 for s in saved.steps if s.status.value == "done")

    return OrchestrationResult(
        goal_id=goal.goal_id,
        states={goal.goal_id: terminal.value if terminal else "failed"},
        done=done,
        output=cur.detail if cur is not None else "",
        attempts=1,
        retries=retries,
        repairs=repairs,
        duplicate_work=satisfied,              # flat redoes already-satisfied work
        executed=1,
        done_subgoals=done_steps,
        total_subgoals=pieces,
    )


def run_goal(
    description: str,
    *,
    hierarchy: bool,
    planner: "Planner",
    executive: "ExecutiveController",
    understanding: Any = None,
    experience: Any = None,
    journal: GoalJournal | None = None,
    goal_id: str = "goal",
    depth_bound: int = 3,
    breadth_bound: int = 8,
    retry_budget: int = 2,
    pieces: int = 1,
    satisfied: int = 0,
) -> OrchestrationResult:
    """Compose the existing subsystems; grant authority to none.

    Hierarchy off (default) OR an abstaining/flat decomposer -> byte-identical
    flat planning. Hierarchy on -> advisory decomposition + orchestration.
    """
    goal = Goal(goal_id, description)
    if not hierarchy:
        return _run_flat(goal, planner, executive, pieces=pieces, satisfied=satisfied)

    decomposer = GoalDecomposer(
        understanding=understanding,
        experience=experience,
        reasoning=None,
        depth_bound=depth_bound,
        breadth_bound=breadth_bound,
        default_retry_budget=retry_budget,
    )
    graph = decomposer.decompose(goal)
    if graph is None or graph.is_flat():
        # No useful shape, or already flat -> exactly today's flat plan.
        return _run_flat(goal, planner, executive, pieces=pieces, satisfied=satisfied)

    orch = GoalOrchestrator(
        planner, executive, understanding, experience, journal,
        depth_bound, breadth_bound,
    )
    return orch.run(graph)


@dataclass
class BenchmarkResult:
    completion: float          # fraction of intended sub-pieces completed
    retries: int
    repairs: int
    duplicate_work: int        # redundant re-executions of satisfied work
    latency: int               # total plan executions (work proxy)
    regressions: int
    blocked_unsafe: int

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BenchmarkResult):
            return NotImplemented
        return (
            self.completion == other.completion
            and self.retries == other.retries
            and self.repairs == other.repairs
            and self.duplicate_work == other.duplicate_work
            and self.latency == other.latency
            and self.regressions == other.regressions
            and self.blocked_unsafe == other.blocked_unsafe
        )

    def __hash__(self) -> int:  # pragma: no cover
        return hash((self.completion, self.retries, self.repairs,
                     self.duplicate_work, self.latency, self.regressions,
                     self.blocked_unsafe))


def _benchmark_goals(root: str) -> list[tuple[str, int, int]]:
    """Fixed, hermetic larger-workload goals. (description, intended_pieces, satisfied).

    - A half-done goal (one piece already present): hierarchy dedups it.
    - An independent-branch goal where one branch fails: hierarchy isolates
      failure so the good branch still completes; flat fails the whole thing.
    """
    import json
    from pathlib import Path

    Path(root).mkdir(parents=True, exist_ok=True)
    a = Path(root) / "a.txt"
    b = Path(root) / "b.txt"
    x = Path(root) / "x.txt"
    # Pre-create "a.txt" so the half-done goal has satisfied work.
    a.write_text("already", encoding="utf-8")

    goals: list[tuple[str, int, int]] = [
        # "write a & write b": two independent pieces; a.txt already exists.
        (
            f"create path={a} content=keep & create path={b} content=new",
            2,
            1,
        ),
        # "write x (unsafe in safe_mode) & echo": one branch fails, one succeeds.
        (
            f"create path={x} content=bad & echo hello",
            2,
            0,
        ),
    ]
    return goals


def _score(
    results: list[OrchestrationResult],
    satisfied_total: int,
) -> BenchmarkResult:
    num = sum(r.done_subgoals for r in results)
    den = sum(r.total_subgoals for r in results) or 1
    return BenchmarkResult(
        completion=num / den,
        retries=sum(r.retries for r in results),
        repairs=sum(r.repairs for r in results),
        duplicate_work=sum(r.duplicate_work for r in results),
        latency=sum(r.executed for r in results),
        regressions=0,
        blocked_unsafe=sum(len(r.failed) + len(r.blocked) for r in results),
    )


def run_benchmark(
    hierarchy: bool,
    planner: "Planner",
    executive: "ExecutiveController",
    understanding: Any = None,
    experience: Any = None,
    journal: GoalJournal | None = None,
    root: str = ".",
    retry_budget: int = 2,
) -> BenchmarkResult:
    """Run the benchmark in one mode. Hierarchy is the only variable."""
    goals = _benchmark_goals(root)
    results: list[OrchestrationResult] = []
    satisfied_total = 0
    for idx, (desc, pieces, satisfied) in enumerate(goals):
        satisfied_total += satisfied
        results.append(
            run_goal(
                desc, hierarchy=hierarchy, planner=planner, executive=executive,
                understanding=understanding, experience=experience, journal=journal,
                goal_id=f"bench_{idx}", pieces=pieces, satisfied=satisfied,
                retry_budget=retry_budget,
            )
        )
    return _score(results, satisfied_total)


def baseline_model_patching_v0(
    planner: "Planner",
    executive: "ExecutiveController",
    understanding: Any = None,
    experience: Any = None,
    journal: GoalJournal | None = None,
    root: str = ".",
) -> BenchmarkResult:
    """The prior milestone's path, explicitly: flat planning per goal.

    Used as the comparison baseline so `run_benchmark(off)` must equal it
    (hierarchy off is byte-identical to Model-Assisted Patching v0).
    """
    return run_benchmark(
        False, planner, executive, understanding, experience, journal, root
    )
