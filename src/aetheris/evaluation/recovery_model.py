"""Recovery drill result and metric models — frozen, additive-only data contracts.

These types belong to evaluation, not ChangeSet.  They measure and verify
rollback outcomes inside hermetic fixtures without introducing new runtime
authority or modifying existing subsystems.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ..trace.model import TraceUnknown, TraceValue


class RollbackClassification(str, Enum):
    EXACT = "exact"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    INVALID = "invalid"


class ImplementationClass(str, Enum):
    EXISTING_SUBSYSTEM_MECHANISM = "existing_subsystem_mechanism"
    FIXTURE_PROTOCOL_IMPLEMENTATION = "fixture_protocol_implementation"
    PURE_CONTRACT_CASE = "pure_contract_case"


@dataclass(frozen=True)
class ExpectedRestoration:
    scenario_id: str
    rollback_kind: str
    eligible_for_exact_restoration: bool
    expected_identity: TraceValue | None
    expected_outcome: str
    expected_unchanged_evidence: tuple[TraceValue, ...]
    expected_authority_delta: int
    expected_safety_invariants: tuple[str, ...]
    expected_unknowns: tuple[str, ...]


@dataclass(frozen=True)
class RollbackObservation:
    scenario_id: str
    change_set_id: str
    receipt_id: str
    observed_identity: TraceValue | None
    evidence_before: tuple[TraceValue, ...]
    evidence_after: tuple[TraceValue, ...]
    authority_before: tuple[tuple[str, str], ...]
    authority_after: tuple[tuple[str, str], ...]
    safety_checks: tuple[tuple[str, bool], ...]
    started_monotonic_ns: int
    finished_monotonic_ns: int
    work_units_reused: TraceValue
    unknowns: tuple[TraceUnknown, ...]


@dataclass(frozen=True)
class ScenarioVerification:
    scenario_id: str
    classification: Literal[
        "exact", "partial", "blocked", "failed",
        "unknown", "not_applicable", "invalid",
    ]
    receipt_valid: bool
    change_link_valid: bool
    restoration_match: TraceValue
    evidence_preserved: TraceValue
    authority_delta: int
    safety_preserved: bool
    sequence_valid: TraceValue
    duration_ns: int
    failures: tuple[str, ...]
    unknowns: tuple[TraceUnknown, ...]
    implementation_class: ImplementationClass = ImplementationClass.PURE_CONTRACT_CASE
    rollback_kind: str = ""
    change_set_id: str = ""
    receipt_id: str = ""


@dataclass(frozen=True)
class RecoveryMetrics:
    exact_count: int = 0
    partial_count: int = 0
    blocked_count: int = 0
    failed_count: int = 0
    unknown_count: int = 0
    not_applicable_count: int = 0
    invalid_count: int = 0
    total_attempted: int = 0
    exact_eligible_attempted: int = 0
    exact_restoration_success_rate: float = 0.0
    partial_restoration_rate: float = 0.0
    blocked_rollback_rate: float = 0.0
    failed_rollback_rate: float = 0.0
    unknown_restoration_rate: float = 0.0
    invalid_claim_rate: float = 0.0
    median_duration_ns: int = 0
    p95_duration_ns: int = 0
    duplicate_work_avoided: int = 0
    duplicate_work_unknown: bool = True
    regressions: tuple[str, ...] = ()
    unsafe_attempts: int = 0
    authority_increase: int = 0
    evidence_preserved: bool = True


@dataclass(frozen=True)
class DrillReport:
    schema_version: int = 1
    run_id: str = ""
    candidate_revision: str = ""
    scenario_results: tuple[ScenarioVerification, ...] = ()
    metrics: RecoveryMetrics = RecoveryMetrics()
    authority_delta: int = 0
    unsafe_attempts: int = 0
    regressions: tuple[str, ...] = ()
    unknowns: tuple[TraceUnknown, ...] = ()
    verdict: Literal["pass", "hold", "reject"] = "hold"