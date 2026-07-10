"""Evaluation: benchmark cases + deterministic scoring."""

from .cases import AMBIGUITY_GUARD_NAMES, ANCHOR_NAMES, EvalCase, default_suite
from .compare import CaseDelta, Comparison, ModelComparison
from .evaluator import CaseResult, Evaluator, Report

__all__ = [
    "ANCHOR_NAMES",
    "AMBIGUITY_GUARD_NAMES",
    "EvalCase",
    "default_suite",
    "CaseDelta",
    "Comparison",
    "ModelComparison",
    "CaseResult",
    "Evaluator",
    "Report",
]

