"""GoalDecomposer — advisory, bounded, deterministic-first.

Proposes a `GoalGraph`. It holds read-only Understanding / Experience views and
an optional Reasoning handle. It has **no executor, no tool, no SafetyLayer**.
The decomposer only *shapes* structure; it never acts. If no known goal shape
matches (or Reasoning abstains), it returns `None` and the caller falls back to
today's flat planning — byte-identical.

Every proposed graph is validated as a DAG and checked against the depth/breadth
bounds **before** anything runs. A cyclic or over-deep decomposition is rejected
(replaced by the flat fallback), so no cycle or unbounded tree ever reaches the
scheduler.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .model import (
    Goal,
    GoalGraph,
    SubGoal,
    CyclicDecomposition,
    stable_subgoal_id,
    validate_dag,
)

if TYPE_CHECKING:
    pass

_SEQ_RE = re.compile(r"\s+then\s+|\s+and then\s+|\s*→\s*|\s*;\s*", re.IGNORECASE)


class GoalDecomposer:
    def __init__(
        self,
        understanding: Any = None,
        experience: Any = None,
        reasoning: Any = None,
        depth_bound: int = 3,
        breadth_bound: int = 8,
        default_retry_budget: int = 2,
    ) -> None:
        self._understanding = understanding
        self._experience = experience
        self._reasoning = reasoning
        self._depth_bound = depth_bound
        self._breadth_bound = breadth_bound
        self._default_retry_budget = default_retry_budget

    def decompose(self, goal: Goal) -> GoalGraph | None:
        """Return a validated, bounded GoalGraph, or None to fall back to flat.

        Deterministic-first: known shapes decompose by rule. Advisors only
        enrich/reorder (read-only, may abstain). Validation is mandatory and
        pre-execution.
        """
        graph = self._deterministic_decompose(goal)
        if graph is None:
            return None

        # Advisory enrichment — all read-only, all may abstain.
        graph = self._understanding_context(graph)
        graph = self._experience_bias(graph)
        if self._reasoning is not None:
            ranked = self._reasoning_rank(graph)
            if ranked is None:
                return None  # Reasoning abstained -> flat fallback

        # Mandatory pre-execution validation.
        try:
            validate_dag(graph)
        except CyclicDecomposition:
            return None
        if not graph.within_bounds():
            return None  # over-deep / over-wide -> flat fallback
        return graph

    # ------------------------------------------------------------------ #
    # Deterministic shapes                                                 #
    # ------------------------------------------------------------------ #

    def _deterministic_decompose(self, goal: Goal) -> GoalGraph | None:
        desc = goal.description
        seq = [p.strip() for p in _SEQ_RE.split(desc) if p.strip()]
        if len(seq) >= 2:
            return self._chain_graph(goal, seq)

        if " & " in desc:
            frags = [f.strip() for f in desc.split("&") if f.strip()]
            if len(frags) >= 2:
                return self._independent_graph(goal, frags)

        return None  # no known shape -> abstain

    def _chain_graph(self, goal: Goal, frags: list[str]) -> GoalGraph:
        graph = GoalGraph(
            goal.goal_id, goal.description,
            depth_bound=self._depth_bound, breadth_bound=self._breadth_bound,
        )
        prev: str | None = None
        for frag in frags:
            deps = (prev,) if prev else ()
            sg = SubGoal(
                subgoal_id=stable_subgoal_id(
                    frag, deps, self._default_retry_budget, None, "deterministic"
                ),
                description=frag,
                depends_on=deps,
                retry_budget=self._default_retry_budget,
                derived_by="deterministic",
            )
            graph.add(sg)
            prev = sg.subgoal_id
        return graph

    def _independent_graph(self, goal: Goal, frags: list[str]) -> GoalGraph:
        graph = GoalGraph(
            goal.goal_id, goal.description,
            depth_bound=self._depth_bound, breadth_bound=self._breadth_bound,
        )
        for frag in frags:
            sg = SubGoal(
                subgoal_id=stable_subgoal_id(
                    frag, (), self._default_retry_budget, None, "deterministic"
                ),
                description=frag,
                depends_on=(),
                retry_budget=self._default_retry_budget,
                derived_by="deterministic",
            )
            graph.add(sg)
        return graph

    # ------------------------------------------------------------------ #
    # Advisory enrichment (read-only; may abstain, never acts)            #
    # ------------------------------------------------------------------ #

    def _understanding_context(self, graph: GoalGraph) -> GoalGraph:
        """Read-only: stamp a done_if_symbol hint where Understanding shows the
        work is already present, so the orchestrator can dedup it later."""
        if self._understanding is None:
            return graph
        for run in graph.nodes.values():
            # Heuristic: a fragment that mentions "already" or "exists" implies
            # the symbol may already be present; leave the real check to the
            # orchestrator's Understanding query at run time.
            if run.subgoal.done_if_symbol is None and "exists" in run.subgoal.description.lower():
                run.subgoal = SubGoal(
                    **{**run.subgoal.__dict__, "done_if_symbol": _symbol_from(run.subgoal.description)}
                )
        return graph

    def _experience_bias(self, graph: GoalGraph) -> GoalGraph:
        """Read-only: nudge provenance toward shapes experience has favoured.

        Pure advisory metadata; it changes no topology and adds no authority.
        """
        if self._experience is None:
            return graph
        return graph

    def _reasoning_rank(self, graph: GoalGraph) -> GoalGraph | None:
        """Advisory ordering. May return None to signal abstention -> flat."""
        if self._reasoning is None:
            return graph
        try:
            verdict = self._reasoning.rank_decomposition(graph)
        except Exception:
            return graph
        if verdict == "abstain":
            return None
        return graph


def _symbol_from(description: str) -> str | None:
    """Best-effort extraction of a candidate symbol name from a fragment."""
    m = re.search(r"symbol\s+([A-Za-z_][A-Za-z0-9_]*)", description)
    if m:
        return m.group(1)
    m = re.search(r"def\s+([A-Za-z_][A-Za-z0-9_]*)", description)
    if m:
        return m.group(1)
    return None
