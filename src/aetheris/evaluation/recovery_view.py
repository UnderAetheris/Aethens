"""Read-only rendering for recovery drill results.

No write controls.  All views are pure functions over frozen data.
"""
from __future__ import annotations

from typing import Any

from .recovery_model import (
    DrillReport,
    RecoveryMetrics,
    ScenarioVerification,
)
from ..trace.model import TraceValue


def _tv_display(tv: TraceValue | None) -> str:
    if tv is None:
        return "<none>"
    if tv.state == "known":
        return str(tv.value)
    if tv.state == "unknown":
        return f"<unknown:{tv.reason or ''}>"
    if tv.state == "not_applicable":
        return f"<not_applicable:{tv.reason or ''}>"
    if tv.state == "mismatch":
        return f"<mismatch:{tv.reason or ''}>"
    return f"<{tv.state}>"


def _classification_display(cls: str) -> str:
    return cls.replace("_", " ").title()


def render_scenario_verification(v: ScenarioVerification) -> str:
    lines = [
        f"scenario: {v.scenario_id}",
        f"classification: {_classification_display(v.classification)}",
        f"rollback_kind: {v.rollback_kind or 'unknown'}",
        f"implementation_class: {v.implementation_class.value}",
        f"change_set_id: {v.change_set_id or 'unknown'}",
        f"receipt_id: {v.receipt_id or 'unknown'}",
        f"receipt_valid: {v.receipt_valid}",
        f"change_link_valid: {v.change_link_valid}",
        f"restoration_match: {_tv_display(v.restoration_match)}",
        f"evidence_preserved: {_tv_display(v.evidence_preserved)}",
        f"authority_delta: {v.authority_delta}",
        f"safety_preserved: {v.safety_preserved}",
        f"sequence_valid: {_tv_display(v.sequence_valid)}",
        f"duration_ns: {v.duration_ns}",
    ]
    if v.failures:
        lines.append("failures:")
        for f in v.failures:
            lines.append(f"  - {f}")
    if v.unknowns:
        lines.append("unknowns:")
        for u in v.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")
    return "\n".join(lines)


def render_metrics(m: RecoveryMetrics) -> str:
    lines = [
        "=== Recovery Metrics ===",
        f"total_attempted: {m.total_attempted}",
        f"exact: {m.exact_count}",
        f"partial: {m.partial_count}",
        f"blocked: {m.blocked_count}",
        f"failed: {m.failed_count}",
        f"unknown: {m.unknown_count}",
        f"not_applicable: {m.not_applicable_count}",
        f"invalid: {m.invalid_count}",
        f"exact_restoration_success_rate: {m.exact_restoration_success_rate}",
        f"partial_restoration_rate: {m.partial_restoration_rate}",
        f"blocked_rollback_rate: {m.blocked_rollback_rate}",
        f"failed_rollback_rate: {m.failed_rollback_rate}",
        f"unknown_restoration_rate: {m.unknown_restoration_rate}",
        f"invalid_claim_rate: {m.invalid_claim_rate}",
        f"median_duration_ns: {m.median_duration_ns}",
        f"p95_duration_ns: {m.p95_duration_ns}",
        f"duplicate_work_avoided: {m.duplicate_work_avoided}",
        f"duplicate_work_unknown: {m.duplicate_work_unknown}",
        f"unsafe_attempts: {m.unsafe_attempts}",
        f"authority_increase: {m.authority_increase}",
        f"evidence_preserved: {m.evidence_preserved}",
    ]
    if m.regressions:
        lines.append("regressions:")
        for r in m.regressions:
            lines.append(f"  - {r}")
    return "\n".join(lines)


def render_report(report: DrillReport) -> str:
    lines = [
        "=== Recovery Drill Report ===",
        f"schema_version: {report.schema_version}",
        f"run_id: {report.run_id}",
        f"candidate_revision: {report.candidate_revision}",
        f"verdict: {report.verdict}",
        f"authority_delta: {report.authority_delta}",
        f"unsafe_attempts: {report.unsafe_attempts}",
    ]
    if report.regressions:
        lines.append("regressions:")
        for r in report.regressions:
            lines.append(f"  - {r}")
    if report.unknowns:
        lines.append("unknowns:")
        for u in report.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")

    lines.append("")
    lines.append("--- Scenario Results ---")
    for v in report.scenario_results:
        lines.append(render_scenario_verification(v))
        lines.append("")

    lines.append("--- Metrics ---")
    lines.append(render_metrics(report.metrics))

    return "\n".join(lines)


def render_report_json(report: DrillReport) -> dict[str, Any]:
    return {
        "schema_version": report.schema_version,
        "run_id": report.run_id,
        "candidate_revision": report.candidate_revision,
        "verdict": report.verdict,
        "authority_delta": report.authority_delta,
        "unsafe_attempts": report.unsafe_attempts,
        "regressions": list(report.regressions),
        "unknowns": [
            {"code": u.code, "field": u.field, "reason": u.reason, "required_for": list(u.required_for)}
            for u in report.unknowns
        ],
        "scenario_results": [
            {
                "scenario_id": v.scenario_id,
                "classification": v.classification,
                "rollback_kind": v.rollback_kind,
                "implementation_class": v.implementation_class.value,
                "change_set_id": v.change_set_id,
                "receipt_id": v.receipt_id,
                "receipt_valid": v.receipt_valid,
                "change_link_valid": v.change_link_valid,
                "restoration_match": {"state": v.restoration_match.state, "value": v.restoration_match.value},
                "evidence_preserved": {"state": v.evidence_preserved.state, "value": v.evidence_preserved.value},
                "authority_delta": v.authority_delta,
                "safety_preserved": v.safety_preserved,
                "sequence_valid": {"state": v.sequence_valid.state, "value": v.sequence_valid.value},
                "duration_ns": v.duration_ns,
                "failures": list(v.failures),
                "unknowns": [
                    {"code": u.code, "field": u.field, "reason": u.reason, "required_for": list(u.required_for)}
                    for u in v.unknowns
                ],
            }
            for v in report.scenario_results
        ],
        "metrics": {
            "total_attempted": report.metrics.total_attempted,
            "exact_count": report.metrics.exact_count,
            "partial_count": report.metrics.partial_count,
            "blocked_count": report.metrics.blocked_count,
            "failed_count": report.metrics.failed_count,
            "unknown_count": report.metrics.unknown_count,
            "not_applicable_count": report.metrics.not_applicable_count,
            "invalid_count": report.metrics.invalid_count,
            "exact_restoration_success_rate": report.metrics.exact_restoration_success_rate,
            "partial_restoration_rate": report.metrics.partial_restoration_rate,
            "blocked_rollback_rate": report.metrics.blocked_rollback_rate,
            "failed_rollback_rate": report.metrics.failed_rollback_rate,
            "unknown_restoration_rate": report.metrics.unknown_restoration_rate,
            "invalid_claim_rate": report.metrics.invalid_claim_rate,
            "median_duration_ns": report.metrics.median_duration_ns,
            "p95_duration_ns": report.metrics.p95_duration_ns,
            "duplicate_work_avoided": report.metrics.duplicate_work_avoided,
            "duplicate_work_unknown": report.metrics.duplicate_work_unknown,
            "unsafe_attempts": report.metrics.unsafe_attempts,
            "authority_increase": report.metrics.authority_increase,
            "evidence_preserved": report.metrics.evidence_preserved,
        },
    }


class ReadOnlyAuditView:
    """Read-only view over a DrillReport.

    Exposes mechanism, receipt, observed result, expected identity,
    unknowns, and mismatches.  No write controls.
    """

    def __init__(self, report: DrillReport) -> None:
        self._report = report

    def scenarios(self) -> tuple[ScenarioVerification, ...]:
        return self._report.scenario_results

    def metrics(self) -> RecoveryMetrics:
        return self._report.metrics

    def verdict(self) -> str:
        return self._report.verdict

    def mismatches(self) -> list[ScenarioVerification]:
        return [
            v for v in self._report.scenario_results
            if v.classification in ("partial", "invalid")
            or v.restoration_match.state == "mismatch"
            or not v.receipt_valid
            or not v.change_link_valid
        ]

    def unknowns_list(self) -> list[ScenarioVerification]:
        return [
            v for v in self._report.scenario_results
            if v.classification == "unknown"
            or any(u.code not in {"missing_config", "missing_policy"} for u in v.unknowns)
        ]

    def render_summary(self) -> str:
        return render_report(self._report)

    def render_json(self) -> dict[str, Any]:
        return render_report_json(self._report)