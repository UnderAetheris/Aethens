"""GoalOrchestrator — a scheduler over the existing spine, not an actor.

Walks a `GoalGraph` and, for each ready leaf, calls the **existing** planner to
produce an ordinary `MultiStepPlan` and the **existing** Executive to run it
through the unchanged `SafetyLayer -> tool` spine. It never executes a tool,
never edits a file, never gates anything. Long-horizon reach comes from *many
sequential validated plans with checkpoints*, not from concurrency: exactly one
plan runs at a time, in a deterministic order, with no background threads.

Failure is contained: a failed subgoal retries within its own bounded budget
(Reflection owns the repair inside the plan); exhausting the budget marks it
`FAILED` and its dependents `BLOCKED`, while independent branches keep going.
Completed work is detected (Understanding facts + the journal) and deduped, so
half-finished goals skip what's already satisfied. Cancellation is a journaled
state transition, never a mid-write kill.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .journal import GoalJournal
from .model import (
    GoalGraph,
    SubGoalRun,
    SubGoalState,
    validate_dag,
)
from .runner import ExecSpy, PlanRunResult, SpineRunner

if TYPE_CHECKING:
    from ..memory.store import MemoryStore
    from ..planner.plan import MultiStepPlan
    from ..planner.planner import Planner

_TERMINAL = frozenset({
    SubGoalState.DONE,
    SubGoalState.FAILED,
    SubGoalState.BLOCKED,
    SubGoalState.CANCELLED,
})

_REPAIR_EVENT = "repair_inserted"


@dataclass
class OrchestrationTick:
    done: bool
    subgoal_id: str | None = None
    to_state: str | None = None
    reason: str = ""


@dataclass
class OrchestrationResult:
    goal_id: str
    states: dict[str, str]
    done: bool
    output: str
    attempts: int = 0
    retries: int = 0
    repairs: int = 0
    duplicate_work: int = 0          # subgoals deduped (already_satisfied)
    executed: int = 0                # subgoals actually run (attempts > 0)
    done_subgoals: int = 0           # subgoals that reached DONE
    total_subgoals: int = 0          # total subgoals in the goal
    blocked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    repairs_via: str = "none"        # "reflection" | "none"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OrchestrationResult):
            return NotImplemented
        return (
            self.output == other.output
            and self.done == other.done
            and self.attempts == other.attempts
            and self.retries == other.retries
            and self.repairs == other.repairs
        )

    def __hash__(self) -> int:  # pragma: no cover - dataclass with list fields
        return hash((self.goal_id, self.output, self.done))


class GoalOrchestrator:
    """Deterministic, single-plan-at-a-time scheduler over the existing spine."""

    def __init__(
        self,
        planner: "Planner",
        executive: Any,
        understanding: Any = None,
        experience: Any = None,
        journal: GoalJournal | None = None,
        depth_bound: int = 3,
        breadth_bound: int = 8,
        runner: Any = None,
        exec_spy: bool = False,
    ) -> None:
        self._planner = planner
        self._executive = executive
        self._understanding = understanding
        self._experience = experience
        self._journal = journal
        self._depth_bound = depth_bound
        self._breadth_bound = breadth_bound
        self._runner = runner or SpineRunner(executive)
        self.exec_spy: ExecSpy | None = None
        self._plans: dict[str, Any] = {}
        if exec_spy:
            self.exec_spy = ExecSpy(executive._controller, executive._memory)
            self._runner = SpineRunner(executive)

    # ------------------------------------------------------------------ #
    # Public run loop                                                     #
    # ------------------------------------------------------------------ #

    def run(self, graph: GoalGraph) -> OrchestrationResult:
        validate_dag(graph)
        self._snapshot(graph)
        while True:
            tick = self.step(graph)
            if tick.done:
                break
        return self._aggregate(graph)

    def run_until(self, graph: GoalGraph, subgoal_id: str) -> OrchestrationResult:
        """Run until `subgoal_id` is terminal (used to simulate an interrupt),
        leaving the rest of the frontier untouched for a later resume."""
        validate_dag(graph)
        self._snapshot(graph)
        while True:
            node = graph.nodes.get(subgoal_id)
            if node is None or node.state in _TERMINAL:
                break
            tick = self.step(graph)
            if tick.done:
                break
        return self._aggregate(graph)

    def step(self, graph: GoalGraph) -> OrchestrationTick:
        """One deterministic tick: pick the next ready leaf and run it.

        Called by the Executive's existing tick loop (no hidden loop of its own).
        """
        node = self._next_ready(graph)
        if node is None:
            return OrchestrationTick(done=True)

        self._transition(graph, node, SubGoalState.EXECUTING, "scheduling")

        # Automatic done-detection + dedup (no re-execution of satisfied work).
        if self._already_satisfied(node, graph):
            self._transition(graph, node, SubGoalState.DONE, "already_satisfied")
            return OrchestrationTick(
                done=False, subgoal_id=node.subgoal.subgoal_id,
                to_state=SubGoalState.DONE.value, reason="already_satisfied",
            )

        plan = self._plan_for(node)
        result: PlanRunResult = self._runner.run(plan, node.subgoal.description)
        node.plan_id = result.plan_id
        self._plans[node.subgoal.subgoal_id] = plan   # keep for rollback (executive deletes the file)
        node.attempts += 1
        node.result = result.output

        if result.failed:
            if node.attempts <= node.subgoal.retry_budget:
                # Subtree-local retry: Reflection owns the repair inside the plan.
                self._transition(
                    graph, node, SubGoalState.READY,
                    f"retry {node.attempts}/{node.subgoal.retry_budget}",
                )
            else:
                self._transition(graph, node, SubGoalState.FAILED, "exhausted retries")
                self._propagate_blocked(graph, node)
        else:
            self._transition(graph, node, SubGoalState.DONE, "executed")

        return OrchestrationTick(
            done=False, subgoal_id=node.subgoal.subgoal_id,
            to_state=node.state.value, reason=node.reason,
        )

    # ------------------------------------------------------------------ #
    # Scheduling                                                          #
    # ------------------------------------------------------------------ #

    def _next_ready(self, graph: GoalGraph) -> SubGoalRun | None:
        ready: list[str] = []
        for sid, run in graph.nodes.items():
            if run.state not in (SubGoalState.PENDING, SubGoalState.READY):
                continue
            deps = run.subgoal.depends_on
            if all(
                graph.nodes[d].state == SubGoalState.DONE
                for d in deps if d in graph.nodes
            ):
                ready.append(sid)
        if not ready:
            return None
        # Deterministic order: topological + stable-ID tiebreak.
        order = graph.topological_order()
        for sid in order:
            if sid in ready:
                return graph.nodes[sid]
        return None

    def _already_satisfied(self, node: SubGoalRun, graph: GoalGraph) -> bool:
        # 1) Journal: this exact stable ID already completed in a prior run.
        if self._journal is not None:
            final = self._journal.reconstruct(graph.goal_id)
            if final.get(node.subgoal.subgoal_id) == SubGoalState.DONE.value:
                return True
        # 2) Understanding: the target symbol already exists (work is done).
        sym = node.subgoal.done_if_symbol
        if sym is not None and self._understanding is not None:
            try:
                if self._understanding.defines(sym):
                    return True
            except Exception:
                pass
        return False

    def _plan_for(self, node: SubGoalRun) -> "MultiStepPlan":
        """Call the EXISTING planner. Skill reuse happens inside it (repo-aware
        selection), so a promoted skill that matches the subgoal is reused."""
        return self._planner.plan_multi(node.subgoal.description, node.subgoal.subgoal_id)

    # ------------------------------------------------------------------ #
    # Transitions + journal                                               #
    # ------------------------------------------------------------------ #

    def _transition(self, graph: GoalGraph, node: SubGoalRun, state: SubGoalState, reason: str) -> None:
        prev = node.state
        node.state = state
        node.reason = reason
        if self._journal is not None:
            self._journal.record(graph.goal_id, {
                "subgoal_id": node.subgoal.subgoal_id,
                "from_state": prev.value,
                "to_state": state.value,
                "reason": reason,
                "plan_id": node.plan_id,
                "attempt": node.attempts,
                "derived_by": node.subgoal.derived_by,
            })
            graph.version += 1
            self._snapshot(graph)

    def _snapshot(self, graph: GoalGraph) -> None:
        if self._journal is not None:
            self._journal.save(graph)

    def _propagate_blocked(self, graph: GoalGraph, failed: SubGoalRun) -> None:
        """Mark every not-yet-terminal dependent BLOCKED (transitive)."""
        changed = True
        while changed:
            changed = False
            for run in graph.nodes.values():
                if run.state not in (SubGoalState.PENDING, SubGoalState.READY):
                    continue
                blocking = [
                    d for d in run.subgoal.depends_on
                    if d in graph.nodes
                    and graph.nodes[d].state in (
                        SubGoalState.FAILED, SubGoalState.BLOCKED, SubGoalState.CANCELLED
                    )
                ]
                if blocking:
                    self._transition(
                        graph, run, SubGoalState.BLOCKED,
                        f"dependency {blocking[0]} failed",
                    )
                    changed = True

    # ------------------------------------------------------------------ #
    # Cancellation (journaled state transition, never a mid-write kill)  #
    # ------------------------------------------------------------------ #

    def cancel(self, graph: GoalGraph, at: str) -> None:
        if at not in graph.nodes:
            return
        self._transition(graph, graph.nodes[at], SubGoalState.CANCELLED, "cancelled")
        for sid in graph.nodes:
            run = graph.nodes[sid]
            if run.state in (SubGoalState.PENDING, SubGoalState.READY) and self._is_descendant(graph, sid, at):
                self._transition(graph, run, SubGoalState.CANCELLED, "cancelled (propagated)")

    def run_with_cancel(self, graph: GoalGraph, at: str) -> OrchestrationResult:
        """Run until `at` is terminal, then cancel it + its un-started descendants."""
        self.run_until(graph, at)
        self.cancel(graph, at)
        return self._aggregate(graph)

    # ------------------------------------------------------------------ #
    # Subtree rollback (revert effects via the tool undo seam)           #
    # ------------------------------------------------------------------ #

    def rollback_subtree(self, graph: GoalGraph, subtree_root_id: str) -> GoalGraph:
        """Revert a subtree's effects via the existing undo seam and reset its
        nodes to PENDING so they can be retried. Sibling subtrees are untouched."""
        if subtree_root_id not in graph.nodes:
            return graph
        ids = self._subtree_ids(graph, subtree_root_id)
        for sid in ids:
            run = graph.nodes[sid]
            plan = self._plans.get(sid) or (
                self._executive._plan_store.load(run.plan_id) if run.plan_id else None
            )
            if plan is not None:
                for step in plan.steps:
                    try:
                        tool = self._executive._controller.registry.get(step.tool)
                    except Exception:
                        continue
                    if tool.undo is not None:
                        try:
                            tool.undo(step.arg)
                        except Exception:
                            pass
            if run.state != SubGoalState.CANCELLED:
                self._transition(graph, run, SubGoalState.PENDING, "rolled_back")
        return graph

    def run_then_rollback(self, graph: GoalGraph, subtree: str) -> OrchestrationResult:
        self.run(graph)
        self.rollback_subtree(graph, subtree)
        return self._aggregate(graph)

    # ------------------------------------------------------------------ #
    # Aggregation                                                         #
    # ------------------------------------------------------------------ #

    def _aggregate(self, graph: GoalGraph) -> OrchestrationResult:
        states = {sid: run.state.value for sid, run in graph.nodes.items()}
        terminal = all(run.state in _TERMINAL for run in graph.nodes.values())
        done = terminal and all(run.state == SubGoalState.DONE for run in graph.nodes.values())
        attempts = sum(run.attempts for run in graph.nodes.values())
        retries = sum(max(0, run.attempts - 1) for run in graph.nodes.values())
        executed = sum(1 for run in graph.nodes.values() if run.attempts > 0)
        duplicate = sum(1 for run in graph.nodes.values() if run.reason == "already_satisfied")
        repairs = self._count_repairs()
        blocked = [sid for sid, run in graph.nodes.items() if run.state == SubGoalState.BLOCKED]
        failed = [sid for sid, run in graph.nodes.items() if run.state == SubGoalState.FAILED]
        cancelled = [sid for sid, run in graph.nodes.items() if run.state == SubGoalState.CANCELLED]
        summary = "; ".join(
            f"{sid}={run.state.value}" for sid, run in graph.nodes.items()
        )
        return OrchestrationResult(
            goal_id=graph.goal_id,
            states=states,
            done=done,
            output=summary,
            attempts=attempts,
            retries=retries,
            repairs=repairs,
        duplicate_work=duplicate,
        executed=executed,
        done_subgoals=sum(1 for run in graph.nodes.values() if run.state == SubGoalState.DONE),
        total_subgoals=len(graph.nodes),
        blocked=blocked,
            failed=failed,
            cancelled=cancelled,
            critical_path=graph.critical_path(),
            repairs_via="reflection" if repairs > 0 else "none",
        )

    def _count_repairs(self) -> int:
        memory: "MemoryStore | None" = getattr(self._executive, "_memory", None)
        if memory is None:
            return 0
        try:
            return sum(1 for e in memory.history() if e.get("kind") == _REPAIR_EVENT)
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    # Graph helpers                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_descendant(graph: GoalGraph, sid: str, ancestor: str) -> bool:
        if sid == ancestor:
            return False
        seen: set[str] = set()
        q = deque([ancestor])
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            for run in graph.nodes.values():
                if cur in run.subgoal.depends_on:
                    if run.subgoal.subgoal_id == sid:
                        return True
                    q.append(run.subgoal.subgoal_id)
        return False

    @staticmethod
    def _subtree_ids(graph: GoalGraph, root: str) -> list[str]:
        ids = [root]
        changed = True
        while changed:
            changed = False
            for run in graph.nodes.values():
                if run.subgoal.subgoal_id in ids:
                    continue
                if any(d in ids for d in run.subgoal.depends_on):
                    ids.append(run.subgoal.subgoal_id)
                    changed = True
        return ids
