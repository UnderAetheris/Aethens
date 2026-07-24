"""Static adapter registry for projecting persisted records into TraceEnvelope.

No plugin loading, dynamic import, entry points, or arbitrary callbacks.
Adapters are pure projections: they do not open files, execute tools, or
mutate runtime state.
"""
from __future__ import annotations

import json
from typing import Any, Protocol

from .canonical import canonical_hash, sha256_hex
from .model import (
    Provenance,
    ReplayContext,
    SourceLocator,
    TraceEnvelope,
    TraceUnknown,
    TraceValue,
)


class AdapterProjectionError(Exception):
    def __init__(self, message: str, source: SourceLocator | None = None, record: Any = None) -> None:
        self.source = source
        self.record = record
        super().__init__(message)


class TraceAdapter(Protocol):
    adapter_id: str
    adapter_version: int

    def supports(self, source: SourceLocator) -> bool:
        ...

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        ...


def _known_value(value: Any, source: str) -> TraceValue:
    return TraceValue(state="known", value=value, source=source)


def _unknown_value(reason: str, source: str | None = None) -> TraceValue:
    return TraceValue(state="unknown", value=None, reason=reason, source=source)


def _na_value(reason: str) -> TraceValue:
    return TraceValue(state="not_applicable", value=None, reason=reason)


def _trace_id_for(
    trace_id: str | None,
    session_id: str | None,
    goal_id: str | None,
    task_id: str | None,
    plan_id: str | None,
) -> str | None:
    if trace_id:
        return trace_id
    if session_id:
        return f"trace_session_{session_id}"
    if goal_id:
        return f"trace_goal_{goal_id}"
    if task_id:
        return f"trace_task_{task_id}"
    if plan_id:
        return f"trace_plan_{plan_id}"
    return None


def _event_id(
    adapter_id: str,
    adapter_version: int,
    source: SourceLocator,
    source_hash_str: str,
) -> str:
    from .canonical import event_id
    return event_id(
        schema_version=1,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        stream_id=source.stream_id,
        line_or_key=source.line_number or source.record_key or source.snapshot_version,
        identity_basis=source_hash_str,
    )


def _base_envelope(
    adapter: TraceAdapter,
    source: SourceLocator,
    record: Any,
    context: ReplayContext,
    subsystem: str,
    capability_id: str,
    event_type: str,
    authority_class: str,
    task_id: str | None = None,
    session_id: str | None = None,
    plan_id: str | None = None,
    goal_id: str | None = None,
    step_id: str | None = None,
    parent_event_id: str | None = None,
    cause_event_ids: tuple[str, ...] = (),
    outcome: TraceValue | None = None,
    unknowns: tuple[TraceUnknown, ...] = (),
    rollback_ref: TraceValue | None = None,
    ordering_basis: str = "stream_sequence",
) -> TraceEnvelope:
    raw_bytes = record.get("_raw_bytes") if isinstance(record, dict) else None
    unknowns = list(unknowns)
    if raw_bytes is not None:
        src_hash = sha256_hex(raw_bytes)
    else:
        src_hash = "unknown"
        unknowns.append(TraceUnknown(
            code="missing_raw_bytes",
            field="source_hash",
            reason="exact source bytes unavailable; cannot compute source_hash",
            required_for=("trace_membership", "hash_verification"),
            source_locator=source.path_hint or source.stream_id,
        ))
    payload_record = {k: v for k, v in record.items() if k != "_raw_bytes"} if isinstance(record, dict) else record
    payload_hash_str = canonical_hash(payload_record)
    evt_id = _event_id(adapter.adapter_id, adapter.adapter_version, source, src_hash)
    trace_id = _trace_id_for(
        context.expected_trace_id, session_id, goal_id, task_id, plan_id
    )
    revision = context.revision
    config_fp = context.config_snapshot
    policy_fp = context.policy_snapshot
    evidence_refs = tuple(
        f"evref_{e.capability_id}_{e.gate_version}" for e in context.evidence_catalog
    )
    recorded_at = _unknown_value("recorded timestamp not captured in source record")
    if isinstance(record, dict):
        ts = record.get("ts") or record.get("timestamp") or record.get("created_at")
        if ts is not None:
            recorded_at = _known_value(ts, "source_record.timestamp")
    return TraceEnvelope(
        schema_version=1,
        adapter_id=adapter.adapter_id,
        adapter_version=adapter.adapter_version,
        event_id=evt_id,
        trace_id=trace_id,
        parent_event_id=parent_event_id,
        cause_event_ids=cause_event_ids,
        task_id=task_id,
        session_id=session_id,
        plan_id=plan_id,
        goal_id=goal_id,
        step_id=step_id,
        subsystem=subsystem,
        capability_id=capability_id,
        event_type=event_type,
        authority_class=authority_class,
        revision=revision,
        config_fingerprint=config_fp,
        policy_fingerprint=policy_fp,
        evidence_refs=evidence_refs,
        source=source,
        source_hash=src_hash,
        payload_hash=payload_hash_str,
        recorded_at=recorded_at,
        stream_sequence=source.line_number,
        logical_order=None,
        ordering_basis=ordering_basis,
        provenance=Provenance(origin="persisted", confidence="exact"),
        outcome=outcome or _na_value("no outcome captured"),
        unknowns=tuple(unknowns),
        rollback_ref=rollback_ref or _na_value("no rollback reference"),
        preserved_raw_bytes=raw_bytes,
        preserved_payload=payload_record,
    )


class MemoryStoreAdapter:
    adapter_id = "memory_store"
    adapter_version = 1

    ADAPTER_ID = "memory_store"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "memory_store"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "MemoryStore adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        data = record.get("data", {})
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if task_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="task_id",
                reason="MemoryStore record has no task_id in data",
                required_for=("trace_membership",),
                source_locator=source.path_hint,
            ))
        session_id = None
        plan_id = None
        goal_id = None
        step_id = None
        kind = record.get("kind", "unknown")
        if kind in ("action_allowed", "action_blocked", "action_preview"):
            authority_class = "execution"
        elif kind == "step_result":
            authority_class = "execution"
        else:
            authority_class = "none"
        outcome = _known_value(kind, "source_record.kind")
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="memory",
                capability_id="memory",
                event_type=kind,
                authority_class=authority_class,
                task_id=task_id,
                session_id=session_id,
                plan_id=plan_id,
                goal_id=goal_id,
                step_id=step_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


class JsonlStoreAdapter:
    adapter_id = "jsonl_store"
    adapter_version = 1

    ADAPTER_ID = "jsonl_store"
    ADAPTER_VERSION = 1

    _SUBSYSTEM_MAP: dict[str, str] = {
        "knowledge": "memory",
        "experience": "memory",
        "learned": "memory",
    }
    _CAPABILITY_MAP: dict[str, str] = {
        "knowledge": "memory",
        "experience": "experience_recording",
        "learned": "skills",
    }

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "jsonl_store"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "JsonlStore adapter requires dict record",
                source=source,
                record=record,
            )
        stream = source.stream_id
        subsystem = self._SUBSYSTEM_MAP.get(stream, "unknown")
        capability_id = self._CAPABILITY_MAP.get(stream, "unknown")
        kind = record.get("kind", "unknown")
        unknowns: list[TraceUnknown] = []
        task_id = record.get("related_task") or record.get("task_id")
        if task_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="task_id",
                reason="JsonlStore record has no task identifier",
                required_for=("trace_membership",),
            ))
        outcome = _known_value(kind, "source_record.kind")
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem=subsystem,
                capability_id=capability_id,
                event_type=kind,
                authority_class="none",
                task_id=task_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


class PlanStoreAdapter:
    adapter_id = "plan_store"
    adapter_version = 1

    ADAPTER_ID = "plan_store"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "plan_store"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "PlanStore adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        task_id = record.get("task_id")
        if task_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="task_id",
                reason="PlanStore sidecar has no task_id",
                required_for=("trace_membership", "plan_replay",),
            ))
        plan_id = source.record_key or task_id
        outcome = _known_value(
            json.dumps(record.get("steps", []), sort_keys=True), "source_record.steps"
        )
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="planner",
                capability_id="planner",
                event_type="plan_snapshot",
                authority_class="none",
                task_id=task_id,
                plan_id=plan_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
                ordering_basis="snapshot_version",
            ),
        )


class ResearchJournalAdapter:
    adapter_id = "research_journal"
    adapter_version = 1

    ADAPTER_ID = "research_journal"
    ADAPTER_VERSION = 1

    _NETWORK_KINDS = {"perimeter_allowed", "perimeter_denied", "fetch"}
    _PERSISTENCE_KINDS = {"bundle", "extracted", "citation"}

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "research_journal"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "ResearchJournal adapter requires dict record",
                source=source,
                record=record,
            )
        kind = record.get("kind", "unknown")
        if kind in self._NETWORK_KINDS:
            authority_class = "network_egress"
        elif kind in self._PERSISTENCE_KINDS:
            authority_class = "persistence"
        else:
            authority_class = "none"
        unknowns: list[TraceUnknown] = []
        outcome = _known_value(kind, "source_record.kind")
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="research",
                capability_id="research",
                event_type=kind,
                authority_class=authority_class,
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


class HierarchyAdapter:
    adapter_id = "hierarchy"
    adapter_version = 1

    ADAPTER_ID = "hierarchy"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "hierarchy_journal"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "Hierarchy adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        goal_id = record.get("goal_id")
        if goal_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="goal_id",
                reason="Hierarchy journal entry has no goal_id",
                required_for=("trace_membership",),
            ))
        subgoal_id = record.get("subgoal_id")
        step_id = subgoal_id
        to_state = record.get("to_state", "unknown")
        outcome = _known_value(to_state, "source_record.to_state")
        ordering_basis = "stream_sequence"
        if source.snapshot_version:
            ordering_basis = "snapshot_version"
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="hierarchy",
                capability_id="hierarchy",
                event_type="goal_transition",
                authority_class="none",
                goal_id=goal_id,
                step_id=step_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
                ordering_basis=ordering_basis,
            ),
        )


class UnattendedAdapter:
    adapter_id = "unattended"
    adapter_version = 1

    ADAPTER_ID = "unattended"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "unattended_journal"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "Unattended adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        session_id = record.get("session_id")
        if session_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="session_id",
                reason="Unattended journal entry has no session_id",
                required_for=("trace_membership",),
            ))
        kind = record.get("kind", "unknown")
        data = record.get("data", {}) if isinstance(record.get("data"), dict) else {}
        if kind == "session_stopped":
            state = data.get("state", "unknown")
            outcome = _known_value(state, "source_record.data.state")
        else:
            outcome = _known_value(kind, "source_record.kind")
        ordering_basis = "stream_sequence"
        if source.snapshot_version:
            ordering_basis = "snapshot_version"
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="unattended",
                capability_id="unattended_supervisor",
                event_type=kind,
                authority_class="none",
                session_id=session_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
                ordering_basis=ordering_basis,
            ),
        )


class UnderstandingAdapter:
    adapter_id = "understanding"
    adapter_version = 1

    ADAPTER_ID = "understanding"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "understanding_journal"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "Understanding adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        version = record.get("version")
        if version is None:
            unknowns.append(TraceUnknown(
                code="missing_snapshot",
                field="version",
                reason="Understanding scan record has no version",
                required_for=("ordering",),
            ))
        outcome = _known_value(
            json.dumps({
                "changed": record.get("changed", []),
                "removed": record.get("removed", []),
                "version": version,
            }, sort_keys=True),
            "source_record.changed_removed_version",
        )
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="understanding",
                capability_id="understanding",
                event_type="scan_report",
                authority_class="none",
                outcome=outcome,
                unknowns=tuple(unknowns),
                ordering_basis="snapshot_version" if version else "stream_sequence",
            ),
        )


class ReliabilityAdapter:
    adapter_id = "reliability"
    adapter_version = 1

    ADAPTER_ID = "reliability"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "reliability_journal"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "Reliability adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        kind = record.get("kind", "unknown")
        source_key = record.get("source_key")
        if source_key is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="source_key",
                reason="Reliability record has no source_key",
                required_for=("trace_membership",),
            ))
        outcome_value: Any
        if kind == "outcome":
            outcome_value = {
                "source_key": source_key,
                "validated": record.get("validated"),
                "contradicted": record.get("contradicted"),
                "event_id": record.get("event_id"),
            }
        else:
            outcome_value = kind
        outcome = _known_value(
            json.dumps(outcome_value, sort_keys=True) if isinstance(outcome_value, dict) else outcome_value,
            "source_record.kind_payload",
        )
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="research",
                capability_id="research_reliability",
                event_type=kind,
                authority_class="persistence",
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


class EvidenceAdapter:
    adapter_id = "evidence"
    adapter_version = 1

    ADAPTER_ID = "evidence"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "evidence_record"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "Evidence adapter requires dict record",
                source=source,
                record=record,
            )
        capability_id = record.get("capability_id", "unknown")
        gate = record.get("gate") or {}
        verdict = gate.get("verdict", "unknown")
        outcome = _known_value(verdict, "source_record.gate.verdict")
        unknowns_list: list[TraceUnknown] = []
        if not record.get("revision"):
            unknowns_list.append(TraceUnknown(
                code="missing_revision",
                field="revision",
                reason="Evidence record has no revision",
                required_for=("revision_mismatch",),
            ))
        if gate.get("output_sha256") in (None, "not_captured_in_v0", ""):
            unknowns_list.append(TraceUnknown(
                code="missing_evidence",
                field="gate.output_sha256",
                reason="No preserved run artifact hash",
                required_for=("decision_verification",),
            ))
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="architecture",
                capability_id=capability_id,
                event_type="adoption_evidence",
                authority_class="none",
                outcome=outcome,
                unknowns=tuple(unknowns_list),
            ),
        )


class SkillLearningAdapter:
    adapter_id = "skill_learning"
    adapter_version = 1

    ADAPTER_ID = "skill_learning"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "skill_learning"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "SkillLearning adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        kind = record.get("kind", "unknown")
        task_id = record.get("related_task") or record.get("task_id")
        if task_id is None:
            unknowns.append(TraceUnknown(
                code="missing_parent",
                field="task_id",
                reason="Skill/learning record has no task identifier",
                required_for=("trace_membership",),
            ))
        outcome = _known_value(kind, "source_record.kind")
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="skills",
                capability_id="skills",
                event_type=kind,
                authority_class="none",
                task_id=task_id,
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


class ModelPatchAdapter:
    adapter_id = "model_patch"
    adapter_version = 1

    ADAPTER_ID = "model_patch"
    ADAPTER_VERSION = 1

    def supports(self, source: SourceLocator) -> bool:
        return source.store_kind == "model_patch"

    def project(
        self, source: SourceLocator, record: Any, context: ReplayContext
    ) -> tuple[TraceEnvelope, ...]:
        if not isinstance(record, dict):
            raise AdapterProjectionError(
                "ModelPatch adapter requires dict record",
                source=source,
                record=record,
            )
        unknowns: list[TraceUnknown] = []
        kind = record.get("kind", "unknown")
        verdict = record.get("verdict", "unknown")
        outcome = _known_value(verdict, "source_record.verdict")
        return (
            _base_envelope(
                adapter=self,
                source=source,
                record=record,
                context=context,
                subsystem="learning",
                capability_id="model_patch",
                event_type=kind,
                authority_class="sandbox_validation",
                outcome=outcome,
                unknowns=tuple(unknowns),
            ),
        )


_ADAPTERS: list[Any] = [
    MemoryStoreAdapter(),
    JsonlStoreAdapter(),
    PlanStoreAdapter(),
    ResearchJournalAdapter(),
    HierarchyAdapter(),
    UnattendedAdapter(),
    UnderstandingAdapter(),
    ReliabilityAdapter(),
    EvidenceAdapter(),
    SkillLearningAdapter(),
    ModelPatchAdapter(),
]

ADAPTERS: tuple[TraceAdapter, ...] = tuple(_ADAPTERS)


def adapter_for(source: SourceLocator) -> TraceAdapter | None:
    for adapter in ADAPTERS:
        if adapter.supports(source):
            return adapter
    return None
