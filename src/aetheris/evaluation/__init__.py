"""Evaluation: benchmark cases + deterministic scoring."""

from .cases import AMBIGUITY_GUARD_NAMES, ANCHOR_NAMES, EvalCase, WorkflowCase, default_suite, skill_workflow_suite
from .compare import CaseDelta, Comparison, ModelComparison, SkillCaseResult, SkillComparison, SkillComparisonResult
from .evaluator import CaseResult, Evaluator, Report

__all__ = [
    "ANCHOR_NAMES",
    "AMBIGUITY_GUARD_NAMES",
    "EvalCase",
    "WorkflowCase",
    "default_suite",
    "skill_workflow_suite",
    "CaseDelta",
    "Comparison",
    "ModelComparison",
    "SkillCaseResult",
    "SkillComparison",
    "SkillComparisonResult",
    "CaseResult",
    "Evaluator",
    "Report",
]

