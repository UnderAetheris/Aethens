"""Hierarchical Task Decomposition & Long-Horizon Execution v0.

A planner that can plan plans, not a new planner. This package is a *scheduler
over advisory structure*, not an actor. It composes the existing subsystems
(planner, Executive, SafetyLayer, Understanding, Experience) and grants
authority to none. Every executable step is the exact same validated
`MultiStepPlan` the Executive runs today.

Default-off until the adoption gate clears.
"""
from __future__ import annotations

from .api import (
    BenchmarkResult,
    baseline_model_patching_v0,
    run_benchmark,
    run_goal,
)
from .decomposer import GoalDecomposer
from .journal import GoalJournal
from .model import (
    CyclicDecomposition,
    Goal,
    GoalGraph,
    SubGoal,
    SubGoalRun,
    SubGoalState,
    stable_subgoal_id,
    validate_dag,
)
from .orchestrator import (
    GoalOrchestrator,
    OrchestrationResult,
    OrchestrationTick,
)
from .runner import ExecSpy, PlanRunResult, SpineRunner

__all__ = [
    "BenchmarkResult",
    "baseline_model_patching_v0",
    "run_benchmark",
    "run_goal",
    "GoalDecomposer",
    "GoalJournal",
    "CyclicDecomposition",
    "Goal",
    "GoalGraph",
    "SubGoal",
    "SubGoalRun",
    "SubGoalState",
    "stable_subgoal_id",
    "validate_dag",
    "GoalOrchestrator",
    "OrchestrationResult",
    "OrchestrationTick",
    "ExecSpy",
    "PlanRunResult",
    "SpineRunner",
]
