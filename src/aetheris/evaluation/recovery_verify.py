"""Pure comparison and scoring for recovery drill outcomes.

No filesystem, network, process, planner, or writer authority.
All verification is deterministic and read-only.

Observations and expectations may be attribute objects or plain mappings
(fixture runners return dicts); both are read through ``_as_record``.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Literal

from ..trace.model import TraceValue
from .recovery_model import (
    ImplementationClass,
    RecoveryMetrics,
    ScenarioVerification,
)

_SOURCE = "recovery_verify"


def _as_record(obj: object) -> object:
    """Read mappings and attribute objects the same way, without copying values."""
    if isinstance(obj, Mapping):
        return SimpleNamespace(**obj)
    return obj


def _tv_repr(tv: TraceValue) -> tuple[str, object]:
    return (tv.state, tv.value)


def _identity_comparable(identity: object) -> TraceValue | None:
    """Return the TraceValue used for identity comparison.

    Prefers an ``ObjectIdentity``-style ``digest``; otherwise accepts a bare
    ``TraceValue`` identity. Anything else is not comparable.
    """
    digest = getattr(identity, "digest", None)
    if isinstance(digest, TraceValue):
        return digest
    if isinstance(identity, TraceValue):
        return identity
    return None


def _compute_duration(observation: object) -> int:
    if hasattr(observation, "finished_monotonic_ns") and hasattr(observation, "started_monotonic_ns"):
        finish = observation.finished_monotonic_ns
        start = observation.started_monotonic_ns
        if isinstance(finish, int) and isinstance(start, int):
            return max(0, finish - start)
    return 0


def _hash_chain_events(events: tuple[object, ...]) -> str:
    h = hashlib.sha256()
    for ev in events:
        if isinstance(ev, bytes):
            h.update(ev)
        elif isinstance(ev, str):
            h.update(ev.encode("utf-8"))
        else:
            h.update(str(ev).encode("utf-8"))
    return h.hexdigest()


def classify_outcome(
    observation: object,
    expected: object,
) -> tuple[Literal[
    "exact", "partial", "blocked", "failed",
    "unknown", "not_applicable", "invalid",
], tuple[str, ...]]:
    observation = _as_record(observation)
    expected = _as_record(expected)
    failures: list[str] = []

    if hasattr(observation, "outcome") and hasattr(expected, "expected_outcome"):
        obs_outcome = observation.outcome
        exp_outcome = expected.expected_outcome

        if obs_outcome == exp_outcome == "succeeded":
            obs_id = getattr(observation, "observed_identity", None)
            exp_id = getattr(expected, "expected_identity", None)
            if obs_id is not None and exp_id is not None:
                obs_cmp = _identity_comparable(obs_id)
                exp_cmp = _identity_comparable(exp_id)
                if obs_cmp is not None and exp_cmp is not None:
                    if obs_cmp.state != "known":
                        return ("unknown", ("observed identity is not known",))
                    if _tv_repr(obs_cmp) == _tv_repr(exp_cmp):
                        return ("exact", ())
                    failures.append("observed identity does not match expected identity")
                    return ("partial", tuple(failures))

        if obs_outcome == "blocked":
            return ("blocked", ())

        if obs_outcome == "failed":
            return ("failed", ())

        if obs_outcome == "partial":
            return ("partial", ("observed partial restoration",))

        if obs_outcome == "unknown":
            return ("unknown", ("outcome is unknown",))

    if hasattr(observation, "outcome") and observation.outcome == "not_attempted":
        return ("not_applicable", ())

    return ("unknown", ("insufficient evidence to classify",))


def verify_receipt_linkage(
    change_set_id: str,
    receipt_change_id: str,
) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    if not change_set_id:
        errors.append("change_set_id is empty")
    if not receipt_change_id:
        errors.append("receipt.change_id is empty")
    if change_set_id and receipt_change_id and change_set_id != receipt_change_id:
        errors.append(f"receipt.change_id {receipt_change_id!r} does not match change_set {change_set_id!r}")
    return (len(errors) == 0, tuple(errors))


# Ordered authority levels. Narrowing (e.g. enabled -> disabled) is not an increase.
# Unrecognized levels fail closed and count as an increase.
_AUTHORITY_RANK: dict[str, int] = {
    "none": 0,
    "off": 0,
    "disabled": 0,
    "advisory": 1,
    "delegated": 2,
    "direct": 3,
    "on": 3,
    "enabled": 3,
}


def verify_authority_delta(
    authority_before: tuple[tuple[str, str], ...],
    authority_after: tuple[tuple[str, str], ...],
) -> tuple[int, tuple[str, ...]]:
    before_rank: dict[str, int] = {}
    for dim, level in authority_before:
        before_rank[dim] = max(before_rank.get(dim, 0), _AUTHORITY_RANK.get(level, 0))
    failures: list[str] = []
    for dim, level in sorted(set(authority_after)):
        rank = _AUTHORITY_RANK.get(level)
        if rank is None or rank > before_rank.get(dim, 0):
            failures.append(f"authority increased: {dim}={level}")
    return (len(failures), tuple(failures))


def verify_safety_invariants(
    safety_checks: tuple[tuple[str, bool], ...],
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    for name, passed in safety_checks:
        if not passed:
            failures.append(f"safety invariant failed: {name}")
    return (len(failures) == 0, tuple(failures))


def verify_evidence_preserved(
    evidence_before: tuple[TraceValue, ...],
    evidence_after: tuple[TraceValue, ...],
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if len(evidence_before) != len(evidence_after):
        failures.append(f"evidence count changed: {len(evidence_before)} -> {len(evidence_after)}")
    for i, (before, after) in enumerate(zip(evidence_before, evidence_after)):
        if _tv_repr(before) != _tv_repr(after):
            failures.append(f"evidence[{i}] changed during rollback")
    return (len(failures) == 0, tuple(failures))


def verify_identity_match(
    observed: TraceValue | None,
    expected: TraceValue | None,
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if observed is None and expected is None:
        return (True, ())
    if observed is None or expected is None:
        failures.append("identity is None where non-None expected")
        return (False, tuple(failures))
    if _tv_repr(observed) != _tv_repr(expected):
        failures.append("observed identity does not match expected identity")
        return (False, tuple(failures))
    return (True, ())


def verify_sequence_order(
    scenario_ids: tuple[str, ...],
    declared_order: tuple[str, ...],
) -> tuple[bool, tuple[str, ...]]:
    failures: list[str] = []
    if not declared_order:
        return (True, ())
    order_map = {sid: idx for idx, sid in enumerate(declared_order)}
    last_idx = -1
    for sid in scenario_ids:
        if sid in order_map:
            current_idx = order_map[sid]
            if current_idx < last_idx:
                failures.append(f"sequence order violation: {sid} at position {current_idx} after {last_idx}")
            last_idx = current_idx
    return (len(failures) == 0, tuple(failures))


def compute_metrics(
    verifications: tuple[ScenarioVerification, ...],
) -> RecoveryMetrics:
    exact = sum(1 for v in verifications if v.classification == "exact")
    partial = sum(1 for v in verifications if v.classification == "partial")
    blocked = sum(1 for v in verifications if v.classification == "blocked")
    failed = sum(1 for v in verifications if v.classification == "failed")
    unknown = sum(1 for v in verifications if v.classification == "unknown")
    not_applicable = sum(1 for v in verifications if v.classification == "not_applicable")
    invalid = sum(1 for v in verifications if v.classification == "invalid")
    total = len(verifications)

    exact_eligible = sum(
        1 for v in verifications
        if v.classification in ("exact", "partial", "failed", "unknown")
    )

    exact_rate = exact / exact_eligible if exact_eligible > 0 else 0.0
    partial_rate = partial / total if total > 0 else 0.0
    blocked_rate = blocked / total if total > 0 else 0.0
    failed_rate = failed / total if total > 0 else 0.0
    unknown_rate = unknown / total if total > 0 else 0.0
    invalid_rate = invalid / total if total > 0 else 0.0

    durations = [v.duration_ns for v in verifications if v.duration_ns > 0]
    durations_sorted = sorted(durations)
    median_ns = durations_sorted[len(durations_sorted) // 2] if durations_sorted else 0
    p95_idx = int(len(durations_sorted) * 0.95)
    p95_ns = durations_sorted[min(p95_idx, len(durations_sorted) - 1)] if durations_sorted else 0

    regressions = tuple(
        v.scenario_id for v in verifications if v.classification == "invalid"
    )

    unsafe = sum(1 for v in verifications if not v.safety_preserved)

    authority_delta = sum(v.authority_delta for v in verifications)

    return RecoveryMetrics(
        exact_count=exact,
        partial_count=partial,
        blocked_count=blocked,
        failed_count=failed,
        unknown_count=unknown,
        not_applicable_count=not_applicable,
        invalid_count=invalid,
        total_attempted=total,
        exact_eligible_attempted=exact_eligible,
        exact_restoration_success_rate=round(exact_rate, 4),
        partial_restoration_rate=round(partial_rate, 4),
        blocked_rollback_rate=round(blocked_rate, 4),
        failed_rollback_rate=round(failed_rate, 4),
        unknown_restoration_rate=round(unknown_rate, 4),
        invalid_claim_rate=round(invalid_rate, 4),
        median_duration_ns=median_ns,
        p95_duration_ns=p95_ns,
        duplicate_work_avoided=0,
        duplicate_work_unknown=True,
        regressions=regressions,
        unsafe_attempts=unsafe,
        authority_increase=authority_delta,
        evidence_preserved=all(
            v.evidence_preserved.state == "known" and v.evidence_preserved.value is True
            for v in verifications
        ),
    )


def determine_verdict(metrics: RecoveryMetrics) -> Literal["pass", "hold", "reject"]:
    if metrics.unsafe_attempts > 0:
        return "reject"
    if metrics.authority_increase > 0:
        return "reject"
    if metrics.invalid_count > 0:
        return "reject"
    if metrics.failed_count > 0 and metrics.exact_count == 0:
        return "hold"
    if metrics.exact_count == metrics.total_attempted and metrics.total_attempted > 0:
        return "pass"
    if metrics.total_attempted == 0:
        return "hold"
    return "hold"


def verify_scenario(
    observation: object,
    expected: object,
    scenario_id: str = "",
    rollback_kind: str = "",
    change_set_id: str = "",
    receipt_id: str = "",
    implementation_class: ImplementationClass = ImplementationClass.PURE_CONTRACT_CASE,
    declared_sequence: tuple[str, ...] = (),
    scenario_ids_in_order: tuple[str, ...] = (),
) -> ScenarioVerification:
    observation = _as_record(observation)
    expected = _as_record(expected)
    classification, class_failures = classify_outcome(observation, expected)

    receipt_valid = True
    change_link_valid = True
    linkage_errors: tuple[str, ...] = ()
    if hasattr(observation, "receipt_id") and hasattr(observation, "change_set_id"):
        receipt_valid, linkage_errors = verify_receipt_linkage(
            observation.change_set_id,
            observation.receipt_id,
        )
        change_link_valid = receipt_valid

    obs_identity = getattr(observation, "observed_identity", None)
    exp_identity = getattr(expected, "expected_identity", None)
    identity_errors: tuple[str, ...] = ()
    if exp_identity is None:
        restoration_match = TraceValue(
            state="not_applicable",
            value=None,
            reason="no expected identity declared for this scenario",
            source=_SOURCE,
        )
    else:
        identity_match, identity_errors = verify_identity_match(obs_identity, exp_identity)
        if identity_match:
            restoration_match = TraceValue(
                state="known", value=True, reason="identity match", source=_SOURCE,
            )
        else:
            restoration_match = TraceValue(
                state="mismatch",
                value={"matched": False, "errors": list(identity_errors)},
                reason="identity mismatch",
                source=_SOURCE,
            )

    authority_before = getattr(observation, "authority_before", ())
    authority_after = getattr(observation, "authority_after", ())
    auth_delta, auth_errors = verify_authority_delta(authority_before, authority_after)

    safety_checks = getattr(observation, "safety_checks", ())
    safety_ok, safety_errors = verify_safety_invariants(safety_checks)

    evidence_before = getattr(observation, "evidence_before", ())
    evidence_after = getattr(observation, "evidence_after", ())
    evidence_ok, evidence_errors = verify_evidence_preserved(evidence_before, evidence_after)

    seq_ok, seq_errors = verify_sequence_order(
        scenario_ids_in_order,
        declared_sequence,
    )

    all_failures = (
        class_failures + linkage_errors + identity_errors + auth_errors
        + safety_errors + evidence_errors + seq_errors
    )

    # An exact restoration claim needs every supporting check to hold.
    if classification == "exact" and not (
        evidence_ok and safety_ok and auth_delta == 0 and receipt_valid and seq_ok
    ):
        classification = "partial"
        all_failures = all_failures + (
            "exact restoration downgraded: a supporting evidence, safety, authority, "
            "linkage, or sequence check failed",
        )

    duration = _compute_duration(observation)

    unknowns = getattr(observation, "unknowns", ())
    if not isinstance(unknowns, tuple):
        unknowns = tuple(unknowns) if unknowns else ()

    if evidence_ok:
        evidence_preserved = TraceValue(
            state="known", value=True, reason="evidence preserved", source=_SOURCE,
        )
    else:
        evidence_preserved = TraceValue(
            state="mismatch",
            value={"preserved": False, "errors": list(evidence_errors)},
            reason="evidence modified",
            source=_SOURCE,
        )

    if seq_ok:
        sequence_valid = TraceValue(
            state="known", value=True, reason="sequence valid", source=_SOURCE,
        )
    else:
        sequence_valid = TraceValue(
            state="mismatch",
            value={"valid": False, "errors": list(seq_errors)},
            reason="sequence violation",
            source=_SOURCE,
        )

    return ScenarioVerification(
        scenario_id=scenario_id,
        classification=classification,
        receipt_valid=receipt_valid,
        change_link_valid=change_link_valid,
        restoration_match=restoration_match,
        evidence_preserved=evidence_preserved,
        authority_delta=auth_delta,
        safety_preserved=safety_ok,
        sequence_valid=sequence_valid,
        duration_ns=duration,
        failures=all_failures,
        unknowns=unknowns,
        implementation_class=implementation_class,
        rollback_kind=rollback_kind,
        change_set_id=change_set_id,
        receipt_id=receipt_id,
    )
