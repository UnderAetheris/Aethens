"""Evaluation: benchmark cases + deterministic scoring."""

from .cases import EvalCase, default_suite
from .evaluator import CaseResult, Evaluator, Report

__all__ = ["EvalCase", "default_suite", "CaseResult", "Evaluator", "Report"]

