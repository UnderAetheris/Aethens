"""Trace envelope data model.

Frozen dataclasses and standard-library types only.  The serialized
representation is strict JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Scalar / container types
# ---------------------------------------------------------------------------

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | dict[str, "JsonValue"] | list["JsonValue"]


# ---------------------------------------------------------------------------
# TraceValue — typed value carrier
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceValue:
    state: Literal["known", "unknown", "not_applicable", "redacted", "mismatch"]
    value: JsonScalar | dict[str, JsonValue] | list[JsonValue] | None
    reason: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.state == "known":
            if self.value is None or self.source is None:
                raise ValueError("known state requires non-null value and source")
        elif self.state == "unknown":
            if self.value is not None or not self.reason:
                raise ValueError("unknown state requires value=None and non-empty reason")
        elif self.state == "not_applicable":
            if self.value is not None or not self.reason:
                raise ValueError("not_applicable requires value=None and non-empty reason")
        elif self.state == "mismatch":
            if not isinstance(self.value, dict) or not self.reason:
                raise ValueError("mismatch requires dict value and reason")


# ---------------------------------------------------------------------------
# TraceUnknown — missing required fact
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceUnknown:
    code: str
    field: str
    reason: str
    required_for: tuple[str, ...]
    source_locator: str | None = None


REQUIRED_UNKNOWN_CODES = (
    "missing_revision",
    "missing_config",
    "missing_policy",
    "missing_evidence",
    "missing_trace_root",
    "missing_parent",
    "missing_cause",
    "missing_snapshot",
    "missing_payload",
    "unsupported_record_version",
    "ambiguous_order",
    "redacted_secret",
    "external_input_not_recorded",
    "adapter_error",
    "hash_mismatch",
)


# ---------------------------------------------------------------------------
# SourceLocator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceLocator:
    store_kind: str
    stream_id: str
    path_hint: str | None = None
    line_number: int | None = None
    record_key: str | None = None
    snapshot_version: str | None = None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    origin: Literal["persisted", "snapshot", "evidence", "context", "derived"]
    derivation_rule: str | None = None
    source_ids: tuple[str, ...] = ()
    confidence: Literal["exact", "deterministic", "partial", "unknown"] = "unknown"


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    capability_id: str
    gate_version: str
    revision: TraceValue


# ---------------------------------------------------------------------------
# ReplayFailure
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplayFailure:
    code: str
    event_id: str | None
    source_id: str | None
    why: str
    required_level: int
    remediation: str


REQUIRED_FAILURE_CODES = (
    "malformed_record",
    "unsupported_record_version",
    "source_hash_mismatch",
    "payload_hash_mismatch",
    "missing_trace_root",
    "missing_parent",
    "missing_cause",
    "causal_cycle",
    "ambiguous_order",
    "missing_revision",
    "revision_mismatch",
    "missing_config",
    "config_mismatch",
    "missing_policy",
    "policy_mismatch",
    "missing_evidence",
    "missing_snapshot",
    "snapshot_journal_conflict",
    "unsupported_reducer",
    "state_divergence",
    "secret_in_trace",
)


# ---------------------------------------------------------------------------
# TraceEnvelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceEnvelope:
    schema_version: int
    adapter_id: str
    adapter_version: int

    event_id: str
    trace_id: str | None
    parent_event_id: str | None
    cause_event_ids: tuple[str, ...]

    task_id: str | None
    session_id: str | None
    plan_id: str | None
    goal_id: str | None
    step_id: str | None

    subsystem: str
    capability_id: str
    event_type: str
    authority_class: str

    revision: TraceValue
    config_fingerprint: TraceValue
    policy_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]

    source: SourceLocator
    source_hash: str
    payload_hash: str
    recorded_at: TraceValue
    stream_sequence: int | None
    logical_order: int | None
    ordering_basis: str

    provenance: Provenance
    outcome: TraceValue
    unknowns: tuple[TraceUnknown, ...]
    rollback_ref: TraceValue


# ---------------------------------------------------------------------------
# ReplayContext
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplayContext:
    revision: TraceValue
    config_snapshot: TraceValue
    policy_snapshot: TraceValue
    evidence_catalog: tuple[EvidenceRef, ...]
    source_catalog: tuple[SourceLocator, ...]
    expected_trace_id: str | None = None
    strict: bool = True


# ---------------------------------------------------------------------------
# ReplayResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReplayResult:
    status: Literal["complete", "incomplete", "invalid", "unsupported"]
    achieved_level: int
    trace_id: str | None
    ordered_events: tuple[TraceEnvelope, ...]
    reconstructed_state: dict[str, JsonValue]
    failures: tuple[ReplayFailure, ...]
    unknowns: tuple[TraceUnknown, ...]
    input_fingerprint: str
    result_fingerprint: str
