"""Evaluation: benchmark cases + deterministic scoring + recovery drill verification."""

from .cases import AMBIGUITY_GUARD_NAMES, ANCHOR_NAMES, EvalCase, WorkflowCase, default_suite, skill_workflow_suite
from .compare import CaseDelta, Comparison, ModelComparison, SkillCaseResult, SkillComparison, SkillComparisonResult
from .evaluator import CaseResult, Evaluator, Report
from .recovery_model import (
    DrillReport,
    ImplementationClass,
    RecoveryMetrics,
    RollbackClassification,
    ExpectedRestoration,
    RollbackObservation,
    ScenarioVerification,
)
from .recovery_verify import (
    classify_outcome,
    compute_metrics,
    determine_verdict,
    verify_identity_match,
    verify_receipt_linkage,
    verify_scenario,
    verify_sequence_order,
    verify_safety_invariants,
)
from .recovery_view import ReadOnlyAuditView, render_metrics, render_report, render_report_json, render_scenario_verification

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
    "DrillReport",
    "ImplementationClass",
    "RecoveryMetrics",
    "RollbackClassification",
    "ExpectedRestoration",
    "RollbackObservation",
    "ScenarioVerification",
    "classify_outcome",
    "compute_metrics",
    "determine_verdict",
    "verify_identity_match",
    "verify_receipt_linkage",
    "verify_scenario",
    "verify_sequence_order",
    "verify_safety_invariants",
    "ReadOnlyAuditView",
    "render_metrics",
    "render_report",
    "render_report_json",
    "render_scenario_verification",
]

