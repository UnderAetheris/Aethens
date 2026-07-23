"""Pure projection from persisted trace evidence to ChangeSet and RollbackReceipt.

No filesystem, network, process, tool, or runtime state access.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..trace.model import (
    ReplayContext,
    ReplayFailure,
    SourceLocator,
    TraceEnvelope,
    TraceUnknown,
    TraceValue,
)
from .canonical import change_id, receipt_id
from .model import (
    ChangeKind,
    ChangeSet,
    InverseReference,
    MutationDisposition,
    ObjectIdentity,
    RestorationConfirmation,
    RollbackKind,
    RollbackOutcome,
    RollbackReceipt,
)


@dataclass(frozen=True)
class MutationEvidence:
    trace_events: tuple[TraceEnvelope, ...]
    before_object: ObjectIdentity | None
    after_object: ObjectIdentity | None
    context: ReplayContext


@dataclass(frozen=True)
class ProjectionResult:
    success: bool
    records: tuple[ChangeSet | RollbackReceipt, ...]
    failures: tuple[ReplayFailure, ...]
    unknowns: tuple[TraceUnknown, ...]
    warnings: tuple[str, ...]


def _tv(state: str, value: Any, reason: str = "", source: str = "projector") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason, source=source)
    return TraceValue(state="unknown", value=None, reason=f"unexpected state {state}", source=source)


def _object_identity_from(
    object_type: str,
    scope: str,
    locator: Any = None,
    digest: Any = None,
    hash_algorithm: str = "unknown",
    size_bytes: Any = None,
    version_ref: Any = None,
) -> ObjectIdentity:
    def _to_tv(v: Any) -> TraceValue:
        if isinstance(v, TraceValue):
            return v
        if v is None:
            return TraceValue(state="unknown", value=None, reason="not provided", source="projector")
        return TraceValue(state="known", value=v, source="projector")

    if locator is None and digest is None:
        locator = _tv("unknown", None, "absent")
        digest = _tv("unknown", None, "absent")
        hash_algorithm = "unknown"
    else:
        locator = _to_tv(locator)
        digest = _to_tv(digest)
    return ObjectIdentity(
        object_type=object_type,
        scope=scope,
        locator=locator,
        hash_algorithm=hash_algorithm,
        digest=digest,
        size_bytes=_to_tv(size_bytes),
        version_ref=_to_tv(version_ref),
    )


_MUTATION_CLASSIFIERS: dict[str, tuple[ChangeKind, MutationDisposition, str]] = {
    "file_edit": (ChangeKind.FILE_EDIT, MutationDisposition.REVERSIBLE, "planner"),
    "plan_edit": (ChangeKind.PLAN_EDIT, MutationDisposition.REVERSIBLE, "planner"),
    "skill_promotion": (ChangeKind.SKILL_PROMOTION, MutationDisposition.REVERSIBLE, "skills"),
    "skill_retirement": (ChangeKind.SKILL_RETIREMENT, MutationDisposition.REVERSIBLE, "skills"),
    "learning_adoption": (ChangeKind.LEARNING_ADOPTION, MutationDisposition.COMPENSATABLE, "learning"),
    "learning_demotion": (ChangeKind.LEARNING_DEMOTION, MutationDisposition.COMPENSATABLE, "learning"),
    "session_checkpoint": (ChangeKind.SESSION_CHECKPOINT, MutationDisposition.REBUILDABLE_SNAPSHOT, "unattended"),
    "research_evidence_append": (ChangeKind.RESEARCH_EVIDENCE_APPEND, MutationDisposition.APPEND_ONLY, "research"),
    "config_toggle": (ChangeKind.CONFIG_TOGGLE, MutationDisposition.REVERSIBLE, "config"),
    "benchmark_adoption": (ChangeKind.BENCHMARK_ADOPTION, MutationDisposition.APPEND_ONLY, "evaluation"),
    "journal_append": (ChangeKind.JOURNAL_APPEND, MutationDisposition.APPEND_ONLY, "memory"),
    "snapshot_update": (ChangeKind.SNAPSHOT_UPDATE, MutationDisposition.REBUILDABLE_SNAPSHOT, "memory"),
    "model_patch_proposal": (ChangeKind.MODEL_PATCH_PROPOSAL, MutationDisposition.EPHEMERAL, "learning"),
    "model_patch_validation": (ChangeKind.MODEL_PATCH_VALIDATION, MutationDisposition.EPHEMERAL, "learning"),
    "experience_append": (ChangeKind.EXPERIENCE_APPEND, MutationDisposition.APPEND_ONLY, "experience_recording"),
    "knowledge_append": (ChangeKind.KNOWLEDGE_APPEND, MutationDisposition.APPEND_ONLY, "memory"),
}


class ChangeSetProjector:
    def project(self, evidence: MutationEvidence) -> ProjectionResult:
        records: list[ChangeSet] = []
        failures: list[ReplayFailure] = []
        unknowns_list: list[TraceUnknown] = []
        warnings: list[str] = []

        if not evidence.trace_events:
            warnings.append("no trace events provided for projection")
            return ProjectionResult(
                success=True, records=tuple(records),
                failures=tuple(failures), unknowns=tuple(unknowns_list), warnings=tuple(warnings),
            )

        primary = evidence.trace_events[0]
        event_type = primary.event_type

        if event_type not in _MUTATION_CLASSIFIERS:
            failures.append(ReplayFailure(
                code="unsupported_reducer",
                event_id=primary.event_id,
                source_id=primary.source.stream_id,
                why=f"unsupported mutation class: {event_type}",
                required_level=3,
                remediation="register a classifier or mark as unsupported_mutation_class",
            ))
            return ProjectionResult(
                success=False, records=tuple(records),
                failures=tuple(failures), unknowns=tuple(unknowns_list), warnings=tuple(warnings),
            )

        change_kind, disposition, owner_subsystem = _MUTATION_CLASSIFIERS[event_type]

        before = evidence.before_object
        after = evidence.after_object
        if before is None and after is None:
            warnings.append("both before and after identity unknown; exact rollback cannot be confirmed")

        rollback_kind_map = {
            ChangeKind.FILE_EDIT: RollbackKind.GIT_REVERT,
            ChangeKind.PLAN_EDIT: RollbackKind.RESTORE_SNAPSHOT,
            ChangeKind.SKILL_PROMOTION: RollbackKind.TOMBSTONE_UNRETIRE,
            ChangeKind.SKILL_RETIREMENT: RollbackKind.TOMBSTONE_UNRETIRE,
            ChangeKind.LEARNING_ADOPTION: RollbackKind.GIT_REVERT,
            ChangeKind.LEARNING_DEMOTION: RollbackKind.GIT_REVERT,
            ChangeKind.SESSION_CHECKPOINT: RollbackKind.RESUME_CHECKPOINT,
            ChangeKind.RESEARCH_EVIDENCE_APPEND: RollbackKind.NOT_APPLICABLE,
            ChangeKind.CONFIG_TOGGLE: RollbackKind.CONFIG_DISABLE,
            ChangeKind.BENCHMARK_ADOPTION: RollbackKind.NOT_APPLICABLE,
            ChangeKind.JOURNAL_APPEND: RollbackKind.NOT_APPLICABLE,
            ChangeKind.SNAPSHOT_UPDATE: RollbackKind.RESTORE_SNAPSHOT,
            ChangeKind.MODEL_PATCH_PROPOSAL: RollbackKind.DISCARD_SANDBOX,
            ChangeKind.MODEL_PATCH_VALIDATION: RollbackKind.DISCARD_SANDBOX,
            ChangeKind.EXPERIENCE_APPEND: RollbackKind.NOT_APPLICABLE,
            ChangeKind.KNOWLEDGE_APPEND: RollbackKind.NOT_APPLICABLE,
            ChangeKind.UNKNOWN: RollbackKind.UNKNOWN,
        }
        rollback_kind = rollback_kind_map.get(change_kind, RollbackKind.UNKNOWN)

        inverse = InverseReference(
            kind=rollback_kind,
            owner_subsystem=owner_subsystem,
            authority_boundary=None,
            target=primary.outcome,
            preconditions=(),
            expected_restore_identity=before,
            authorization_required=_tv("unknown", None, "authorization not captured in source record"),
        )

        cap_id = primary.capability_id or "unknown"
        auth_class = primary.authority_class or "none"

        trace_id = primary.trace_id if isinstance(primary.trace_id, TraceValue) else _tv("known", primary.trace_id or "unknown", "trace_id captured")
        task_id = primary.task_id if isinstance(primary.task_id, TraceValue) else _tv("known", primary.task_id or "unknown", "task_id captured")
        session_id = primary.session_id if isinstance(primary.session_id, TraceValue) else _tv("unknown", None, "session_id not captured")
        plan_id = primary.plan_id if isinstance(primary.plan_id, TraceValue) else _tv("unknown", None, "plan_id not captured")
        revision = primary.revision
        config_fp = primary.config_fingerprint
        policy_fp = primary.policy_fingerprint
        evidence_refs = primary.evidence_refs
        provenance = primary.provenance
        observed_at = primary.recorded_at
        source_event_ids = tuple(ev.event_id for ev in evidence.trace_events)

        if before is None:
            unknowns_list.append(TraceUnknown(
                code="missing_payload",
                field="before",
                reason="before-state identity is not persisted",
                required_for=("rollback_verification",),
            ))
        if after is None:
            unknowns_list.append(TraceUnknown(
                code="missing_payload",
                field="after",
                reason="after-state identity is not persisted",
                required_for=("restoration_verification",),
            ))

        target = _object_identity_from(
            object_type=event_type,
            scope=primary.subsystem or "unknown",
            locator=primary.task_id or primary.event_id,
            digest=primary.payload_hash,
        )

        if before is None:
            before = _object_identity_from(
                object_type=event_type, scope=primary.subsystem or "unknown",
            )
        if after is None:
            after = _object_identity_from(
                object_type=event_type, scope=primary.subsystem or "unknown",
            )

        cs = ChangeSet(
            schema_version=1,
            change_id="",
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            capability_id=cap_id,
            owner_subsystem=owner_subsystem,
            change_kind=change_kind,
            disposition=disposition,
            authority_class=auth_class,
            target=target,
            before=before,
            after=after,
            inverse=inverse,
            rollback_ref=_tv("unknown", None, "rollback reference not captured in source record"),
            revision=revision,
            config_fingerprint=config_fp,
            policy_fingerprint=policy_fp,
            evidence_refs=evidence_refs,
            source_event_ids=source_event_ids,
            provenance=provenance,
            unknowns=tuple(unknowns_list),
            observed_at=observed_at,
        )
        cs = _make_change_set_from_projection(cs)
        records.append(cs)

        return ProjectionResult(
            success=True, records=tuple(records),
            failures=tuple(failures), unknowns=tuple(cs.unknowns), warnings=tuple(warnings),
        )


def _make_change_set_from_projection(cs: ChangeSet) -> ChangeSet:
    try:
        derived = change_id(cs)
        if cs.change_id != derived:
            return ChangeSet(change_id=derived, **{f.name: getattr(cs, f.name) for f in ChangeSet.__dataclass_fields__.values() if f.name != "change_id"})
    except Exception:
        pass
    return cs


class ReceiptProjector:
    def correlate(
        self,
        change_set: ChangeSet,
        rollback_events: tuple[TraceEnvelope, ...],
        context: ReplayContext,
    ) -> ProjectionResult:
        records: list[RollbackReceipt] = []
        failures: list[ReplayFailure] = []
        unknowns_list: list[TraceUnknown] = []
        warnings: list[str] = []

        if not rollback_events:
            warnings.append("no rollback events provided for correlation")
            return ProjectionResult(
                success=True, records=tuple(records),
                failures=tuple(failures), unknowns=tuple(unknowns_list), warnings=tuple(warnings),
            )

        primary = rollback_events[0]
        outcome_map = {
            "succeeded": RollbackOutcome.SUCCEEDED,
            "failed": RollbackOutcome.FAILED,
            "partial": RollbackOutcome.PARTIAL,
            "blocked": RollbackOutcome.BLOCKED,
            "not_attempted": RollbackOutcome.NOT_ATTEMPTED,
            "unknown": RollbackOutcome.UNKNOWN,
        }
        outcome_str = primary.outcome.value if primary.outcome and primary.outcome.value else "unknown"
        outcome = outcome_map.get(outcome_str, RollbackOutcome.UNKNOWN)

        if change_set.before is None or change_set.after is None:
            warnings.append("linked change_set has unknown before/after; confirmation cannot be exact")

        pre = change_set.after if change_set.after is not None else _object_identity_from(
            object_type=change_set.change_kind.value, scope=change_set.owner_subsystem,
        )
        post = change_set.before if change_set.before is not None else _object_identity_from(
            object_type=change_set.change_kind.value, scope=change_set.owner_subsystem,
        )

        expected = change_set.before
        observed = post
        verifier = primary.provenance

        mismatches: list[str] = []
        if expected is not None and observed is not None:
            if expected.object_type != observed.object_type:
                mismatches.append("object_type")
            if expected.scope != observed.scope:
                mismatches.append("scope")
            if expected.digest.state == "known" and observed.digest.state == "known":
                if str(expected.digest.value) != str(observed.digest.value):
                    mismatches.append("digest")
            elif expected.digest.state != "unknown" or observed.digest.state != "unknown":
                mismatches.append("digest_unknown")

        has_required_unknowns = any(
            u.code in ("missing_revision", "missing_config", "missing_evidence")
            for u in rollback_events[0].unknowns
        )
        has_known_mismatches = bool(mismatches)
        verifier_known = verifier.origin != "unknown" if verifier else False

        if outcome == RollbackOutcome.SUCCEEDED and not has_known_mismatches and verifier_known and not has_required_unknowns:
            confirmation = RestorationConfirmation(
                status="confirmed",
                expected=expected,
                observed=observed,
                verifier=_tv("known", verifier.origin, verifier.derivation_rule or "projector"),
                compared_fields=("object_type", "scope", "digest"),
                mismatches=tuple(mismatches),
            )
        elif outcome in (RollbackOutcome.SUCCEEDED, RollbackOutcome.PARTIAL) and not has_known_mismatches:
            status = "confirmed" if outcome == RollbackOutcome.SUCCEEDED else "partially_confirmed"
            confirmation = RestorationConfirmation(
                status=status,
                expected=expected,
                observed=observed,
                verifier=_tv("known", verifier.origin, verifier.derivation_rule or "projector"),
                compared_fields=("object_type", "scope", "digest"),
                mismatches=tuple(mismatches),
            )
        elif outcome == RollbackOutcome.FAILED:
            confirmation = RestorationConfirmation(
                status="not_confirmed",
                expected=expected,
                observed=observed,
                verifier=_tv("unknown", None, "rollback failed"),
                compared_fields=("object_type", "scope", "digest"),
                mismatches=tuple(mismatches),
            )
        else:
            confirmation = RestorationConfirmation(
                status="unknown",
                expected=expected,
                observed=observed,
                verifier=_tv("unknown", None, "verification incomplete"),
                compared_fields=("object_type", "scope", "digest"),
                mismatches=tuple(mismatches),
            )

        rollback_group_id = _tv("known", f"grp_{change_set.change_id}")
        parent_receipt_id = _tv("not_applicable", None, "first in group")

        rr = RollbackReceipt(
            schema_version=1,
            receipt_id="",
            change_id=change_set.change_id,
            trace_id=change_set.trace_id,
            rollback_group_id=rollback_group_id,
            sequence_index=0,
            parent_receipt_id=parent_receipt_id,
            depends_on_receipt_ids=(),
            rollback_kind=change_set.inverse.kind,
            rollback_target=change_set.target,
            outcome=outcome,
            observed_pre_rollback=pre,
            observed_post_rollback=post,
            confirmation=confirmation,
            revision=primary.revision,
            config_fingerprint=primary.config_fingerprint,
            policy_fingerprint=primary.policy_fingerprint,
            evidence_refs=primary.evidence_refs,
            source_event_ids=tuple(ev.event_id for ev in rollback_events),
            provenance=primary.provenance,
            unknowns=tuple(unknowns_list),
            attempted_at=primary.recorded_at,
            confirmed_at=_tv("unknown", None, "confirmation timestamp not captured"),
        )
        rr = _make_receipt_from_projection(rr)
        records.append(rr)

        return ProjectionResult(
            success=True, records=tuple(records),
            failures=tuple(failures), unknowns=tuple(unknowns_list), warnings=tuple(warnings),
        )


def _make_receipt_from_projection(rr: RollbackReceipt) -> RollbackReceipt:
    try:
        derived = receipt_id(rr)
        if rr.receipt_id != derived:
            return RollbackReceipt(receipt_id=derived, **{f.name: getattr(rr, f.name) for f in RollbackReceipt.__dataclass_fields__.values() if f.name != "receipt_id"})
    except Exception:
        pass
    return rr


def change_set_to_envelope(change_set: ChangeSet, context: ReplayContext) -> TraceEnvelope:
    from ..trace.adapters import _base_envelope

    source = SourceLocator(
        store_kind="change_set",
        stream_id=change_set.capability_id,
        path_hint=change_set.change_id,
        line_number=None,
        record_key=change_set.change_id,
        snapshot_version=None,
    )
    record = {
        "change_id": change_set.change_id,
        "change_kind": change_set.change_kind.value,
        "capability_id": change_set.capability_id,
        "authority_class": change_set.authority_class,
    }
    return _base_envelope(
        adapter=type("_ChangeSetAdapter", (), {"adapter_id": "change_set", "adapter_version": 1})(),
        source=source,
        record=record,
        context=context,
        subsystem=change_set.owner_subsystem,
        capability_id=change_set.capability_id,
        event_type="change_set_observed",
        authority_class="none",
        task_id=change_set.task_id.value if isinstance(change_set.task_id, TraceValue) and change_set.task_id.state == "known" else None,
        session_id=change_set.session_id.value if isinstance(change_set.session_id, TraceValue) and change_set.session_id.state == "known" else None,
        plan_id=change_set.plan_id.value if isinstance(change_set.plan_id, TraceValue) and change_set.plan_id.state == "known" else None,
    )


def rollback_receipt_to_envelope(
    receipt: RollbackReceipt,
    change_set: ChangeSet,
    context: ReplayContext,
) -> TraceEnvelope:
    from ..trace.adapters import _base_envelope

    source = SourceLocator(
        store_kind="rollback_receipt",
        stream_id=change_set.capability_id,
        path_hint=receipt.receipt_id,
        line_number=None,
        record_key=receipt.receipt_id,
        snapshot_version=None,
    )
    record = {
        "receipt_id": receipt.receipt_id,
        "change_id": receipt.change_id,
        "rollback_kind": receipt.rollback_kind.value,
    }
    return _base_envelope(
        adapter=type("_RollbackReceiptAdapter", (), {"adapter_id": "rollback_receipt", "adapter_version": 1})(),
        source=source,
        record=record,
        context=context,
        subsystem=change_set.owner_subsystem,
        capability_id=change_set.capability_id,
        event_type="rollback_receipt_observed",
        authority_class="none",
        task_id=change_set.task_id.value if isinstance(change_set.task_id, TraceValue) and change_set.task_id.state == "known" else None,
        session_id=change_set.session_id.value if isinstance(change_set.session_id, TraceValue) and change_set.session_id.state == "known" else None,
        plan_id=change_set.plan_id.value if isinstance(change_set.plan_id, TraceValue) and change_set.plan_id.state == "known" else None,
        parent_event_id=change_set.change_id,
        cause_event_ids=tuple(receipt.source_event_ids),
    )
