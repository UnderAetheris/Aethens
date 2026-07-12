"""Hierarchical decomposition data model.

Advisory structure only. A `GoalGraph` is a DAG of `SubGoal`s; each `SubGoal`
resolves to an *ordinary* `MultiStepPlan` that the existing Executive runs
through the unchanged spine. The graph holds **no execution handle** — it only
describes *which existing plan to run next and what to do with its result*.

Stable, content-derived `subgoal_id`s power dedup and resume: a completed ID
is never re-run. All of this is pure data + pure functions; no tools, no
SafetyLayer, no writer is reachable from this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SubGoalState(str, Enum):
    PENDING = "pending"        # dependencies not yet satisfied
    READY = "ready"            # all deps done; eligible to schedule
    PLANNING = "planning"      # existing planner is producing its MultiStepPlan
    EXECUTING = "executing"    # existing Executive is running that plan
    DONE = "done"              # completed (executed OR detected already-satisfied)
    FAILED = "failed"          # exhausted its retry budget
    BLOCKED = "blocked"        # a dependency failed
    CANCELLED = "cancelled"


# States from which a node can no longer change (terminal for scheduling).
_TERMINAL = frozenset({
    SubGoalState.DONE,
    SubGoalState.FAILED,
    SubGoalState.BLOCKED,
    SubGoalState.CANCELLED,
})


class CyclicDecomposition(Exception):
    """Raised when a proposed GoalGraph is not a valid DAG (has a cycle)."""


@dataclass(frozen=True)
class SubGoal:
    """One bounded unit of work. Frozen: the graph topology never mutates in place.

    `subgoal_id` is **stable + content-derived** so the same subgoal shape always
    maps to the same ID — that is what makes dedup and resume free.
    """

    subgoal_id: str                 # STABLE, content-derived (deterministic dedup key)
    description: str
    depends_on: tuple[str, ...] = ()      # subgoal_ids this waits on (DAG edges)
    retry_budget: int = 2                 # subtree-local, bounded
    skill_hint: str | None = None         # a promoted skill that may satisfy it
    derived_by: str = "deterministic"     # "deterministic" | "reasoning" | "experience"
    # Optional done-detection hook: if this symbol already exists (per Understanding),
    # the subgoal is satisfied without execution.
    done_if_symbol: str | None = None


@dataclass
class SubGoalRun:
    """Runtime state for one SubGoal within a GoalGraph."""

    subgoal: SubGoal
    state: SubGoalState = SubGoalState.PENDING
    attempts: int = 0
    plan_id: str | None = None            # the ordinary MultiStepPlan produced for it
    result: str = ""                       # summary; full detail in journals
    reason: str = ""                       # provenance of the current state transition

    def to_dict(self) -> dict[str, Any]:
        return {
            "subgoal_id": self.subgoal.subgoal_id,
            "description": self.subgoal.description,
            "depends_on": list(self.subgoal.depends_on),
            "retry_budget": self.subgoal.retry_budget,
            "skill_hint": self.subgoal.skill_hint,
            "derived_by": self.subgoal.derived_by,
            "done_if_symbol": self.subgoal.done_if_symbol,
            "state": self.state.value,
            "attempts": self.attempts,
            "plan_id": self.plan_id,
            "result": self.result,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SubGoalRun":
        return cls(
            subgoal=SubGoal(
                subgoal_id=d["subgoal_id"],
                description=d["description"],
                depends_on=tuple(d.get("depends_on", ())),
                retry_budget=d.get("retry_budget", 2),
                skill_hint=d.get("skill_hint"),
                derived_by=d.get("derived_by", "deterministic"),
                done_if_symbol=d.get("done_if_symbol"),
            ),
            state=SubGoalState(d["state"]),
            attempts=d.get("attempts", 0),
            plan_id=d.get("plan_id"),
            result=d.get("result", ""),
            reason=d.get("reason", ""),
        )


@dataclass
class GoalGraph:
    """A validated DAG of subgoals for one larger goal.

    The graph is pure structure + per-node runtime state. It never holds a tool,
    a SafetyLayer, or an Executive — only the IDs of ordinary plans that the
    existing spine will run.
    """

    goal_id: str
    root_description: str
    version: int = 1
    nodes: dict[str, SubGoalRun] = field(default_factory=dict)
    depth_bound: int = 3
    breadth_bound: int = 8

    # ------------------------------------------------------------------ #
    # Mutation (all additive; topology is fixed at construction)         #
    # ------------------------------------------------------------------ #

    def add(self, subgoal: SubGoal, state: SubGoalState = SubGoalState.PENDING) -> SubGoalRun:
        run = SubGoalRun(subgoal=subgoal, state=state)
        self.nodes[subgoal.subgoal_id] = run
        return run

    # ------------------------------------------------------------------ #
    # DAG properties                                                      #
    # ------------------------------------------------------------------ #

    def is_dag(self) -> bool:
        """True iff the dependency graph is acyclic (Kahn's algorithm)."""
        indeg = {sid: 0 for sid in self.nodes}
        for run in self.nodes.values():
            for dep in run.subgoal.depends_on:
                if dep in indeg:
                    indeg[run.subgoal.subgoal_id] += 1   # edge points INTO this node
        ready = [sid for sid, d in indeg.items() if d == 0]
        done = 0
        while ready:
            nxt = ready.pop()
            done += 1
            for run in self.nodes.values():
                if nxt in run.subgoal.depends_on:
                    indeg[run.subgoal.subgoal_id] -= 1
                    if indeg[run.subgoal.subgoal_id] == 0:
                        ready.append(run.subgoal.subgoal_id)
        return done == len(self.nodes)

    def depth_of(self, subgoal_id: str) -> int:
        """Longest dependency chain ending at `subgoal_id` (0 = root-level)."""
        run = self.nodes.get(subgoal_id)
        if run is None:
            return 0
        if not run.subgoal.depends_on:
            return 0
        return 1 + max(self.depth_of(d) for d in run.subgoal.depends_on if d in self.nodes)

    def max_depth(self) -> int:
        return max((self.depth_of(sid) for sid in self.nodes), default=0)

    def breadth_per_level(self) -> list[int]:
        """Count of nodes at each depth level (for breadth-bound checks)."""
        levels: dict[int, int] = {}
        for sid in self.nodes:
            levels[self.depth_of(sid)] = levels.get(self.depth_of(sid), 0) + 1
        return [levels[k] for k in sorted(levels)]

    def within_bounds(self) -> bool:
        if self.max_depth() > self.depth_bound:
            return False
        return all(b <= self.breadth_bound for b in self.breadth_per_level())

    def topological_order(self) -> list[str]:
        """Deterministic topological order: by depth, then stable ID tiebreak."""
        return sorted(self.nodes, key=lambda sid: (self.depth_of(sid), sid))

    def critical_path(self) -> list[str]:
        """Longest dependency chain (by node count) from a root to a leaf."""
        best: list[str] = []

        def walk(sid: str, path: list[str]) -> None:
            nonlocal best
            here = path + [sid]
            if len(here) > len(best):
                best = here
            run = self.nodes.get(sid)
            if run is None:
                return
            children = [
                other.subgoal.subgoal_id
                for other in self.nodes.values()
                if sid in other.subgoal.depends_on
            ]
            if not children:
                return
            for c in sorted(children):
                walk(c, here)

        for sid in self.topological_order():
            run = self.nodes[sid]
            if not run.subgoal.depends_on:
                walk(sid, [])
        return best

    def is_flat(self) -> bool:
        """True iff the graph is a single node with no dependencies.

        A flat graph is byte-identical to running the whole goal as one plan.
        """
        return len(self.nodes) == 1 and not next(iter(self.nodes.values())).subgoal.depends_on

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "root_description": self.root_description,
            "version": self.version,
            "depth_bound": self.depth_bound,
            "breadth_bound": self.breadth_bound,
            "nodes": [r.to_dict() for r in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GoalGraph":
        g = cls(
            goal_id=d["goal_id"],
            root_description=d["root_description"],
            version=d.get("version", 1),
            depth_bound=d.get("depth_bound", 3),
            breadth_bound=d.get("breadth_bound", 8),
        )
        for nd in d.get("nodes", []):
            run = SubGoalRun.from_dict(nd)
            g.nodes[run.subgoal.subgoal_id] = run
        return g


def stable_subgoal_id(
    description: str,
    depends_on: tuple[str, ...],
    retry_budget: int,
    skill_hint: str | None,
    derived_by: str,
) -> str:
    """Deterministic, content-derived ID. Same subgoal shape -> same ID.

    Powers dedup + resume: a completed ID is never re-run, and a resumed run
    recognises previously-completed work by ID alone.
    """
    payload = json.dumps(
        [description, sorted(depends_on), retry_budget, skill_hint, derived_by],
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"sg_{digest}"


@dataclass(frozen=True)
class Goal:
    """A larger goal handed to the decomposer/orchestrator."""

    goal_id: str
    description: str


def validate_dag(graph: GoalGraph) -> None:
    """Raise CyclicDecomposition if the graph is not a valid DAG.

    Called pre-execution so no cycle ever reaches the scheduler.
    """
    if not graph.is_dag():
        raise CyclicDecomposition(graph.goal_id)
