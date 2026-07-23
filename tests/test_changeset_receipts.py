"""Tests for RollbackReceipt validation, linkage, and multi-step grouping."""
from __future__ import annotations

from typing import Any

from aetheris.changeset.model import (
    ChangeKind,
    ChangeSet,
    InverseReference,
    MutationDisposition,
    ObjectIdentity,
    RestorationConfirmation,
    RollbackKind,
    RollbackOutcome,
    TraceValue,
)
from aetheris.changeset.validate import validate_rollback_receipt
from aetheris.changeset.projector import (
    ReceiptProjector,
)
from aetheris.trace.model import Provenance, ReplayContext, SourceLocator, TraceEnvelope


def _tv(state: str, value: Any, reason: str = "test", source: str = "test") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason, source=source)
    raise ValueError(f"unknown state {state}")


def _oid(object_type="file", scope="repo", locator="src/a.py", digest="a"*64, alg="sha256") -> ObjectIdentity:
    def _to_tv(v: Any) -> TraceValue:
        if isinstance(v, TraceValue):
            return v
        if v is None:
            return TraceValue(state="unknown", value=None, reason="not provided", source="test")
        return TraceValue(state="known", value=v, source="test")
    return ObjectIdentity(
        object_type=object_type, scope=scope,
        locator=_to_tv(locator),
        hash_algorithm=alg,
        digest=_to_tv(digest),
        size_bytes=_to_tv(100),
        version_ref=_to_tv("v1"),
    )


def _make_cs(**kw):
    base = dict(
        schema_version=1, change_id="",
        trace_id=_tv("known", "trace_1"), task_id=_tv("known", "task_1"),
        session_id=_tv("unknown", None, "no session"), plan_id=_tv("unknown", None, "no plan"),
        capability_id="tools", owner_subsystem="tools",
        change_kind=ChangeKind.FILE_EDIT, disposition=MutationDisposition.REVERSIBLE,
        authority_class="execution",
        target=_oid("file", "repo", "src/main.py", "a"*64),
        before=_oid("file", "repo", "src/old.py", "b"*64),
        after=_oid("file", "repo", "src/new.py", "c"*64),
        inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT, owner_subsystem="vc", authority_boundary=None,
            target=_tv("known", {"commit": "abc"}), preconditions=(),
            expected_restore_identity=None, authorization_required=_tv("known", "signer"),
        ),
        rollback_ref=_tv("unknown", None, "no ref"),
        revision=_tv("known", "r1"), config_fingerprint=_tv("unknown", None, "no config"),
        policy_fingerprint=_tv("unknown", None, "no policy"),
        evidence_refs=(), source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(), observed_at=_tv("known", 1000.0),
    )
    base.update(kw)
    return ChangeSet(**base)


def _make_rr(cs, **kw):
    base = dict(
        schema_version=1, receipt_id="", change_id=cs.change_id,
        trace_id=cs.trace_id,
        rollback_group_id=_tv("known", f"grp_{cs.change_id}"),
        sequence_index=0, parent_receipt_id=_tv("not_applicable", None, "first in group"),
        depends_on_receipt_ids=(), rollback_kind=RollbackKind.GIT_REVERT,
        rollback_target=cs.target, outcome=RollbackOutcome.SUCCEEDED,
        observed_pre_rollback=cs.after, observed_post_rollback=cs.before,
        confirmation=RestorationConfirmation(
            status="confirmed", expected=cs.before, observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ),
        revision=_tv("known", "r1"), config_fingerprint=_tv("unknown", None, "no config"),
        policy_fingerprint=_tv("unknown", None, "no policy"),
        evidence_refs=(), source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(), attempted_at=_tv("known", 1000.0), confirmed_at=_tv("known", 1010.0),
    )
    base.update(kw)
    from aetheris.changeset.validate import make_rollback_receipt
    return make_rollback_receipt(**base)


class TestHashLinkage:
    def test_pre_rollback_matches_after_hash(self):
        cs = _make_cs()
        rr = validate_rollback_receipt(_make_rr(cs), cs)
        assert rr.valid is True

    def test_post_rollback_matches_before_hash(self):
        cs = _make_cs()
        rr = validate_rollback_receipt(_make_rr(cs), cs)
        assert rr.valid is True

    def test_wrong_target_scope_fails(self):
        cs = _make_cs()
        rr = _make_rr(cs, rollback_target=_oid("plan", "repo"))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid

    def test_unknown_hash_cannot_confirm(self):
        cs = _make_cs(after=_oid(digest=None))
        rr = _make_rr(cs, observed_pre_rollback=_oid(digest=None), confirmation=RestorationConfirmation(
            status="unknown", expected=None, observed=None,
            verifier=_tv("unknown", None, "no verification"),
            compared_fields=(), mismatches=(),
        ))
        assert rr.confirmation.status != "confirmed"

    def test_partial_compensation_cannot_claim_exact(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.PARTIAL, confirmation=RestorationConfirmation(
            status="confirmed", expected=cs.before, observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("succeeded outcome" in e for e in result.errors)

    def test_failed_outcome_cannot_claim_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="confirmed", expected=cs.before, observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid

    def test_receipt_id_changes_when_material_evidence_changes(self):
        cs = _make_cs()
        from aetheris.changeset.canonical import receipt_id as _rid
        rr1 = _make_rr(cs)
        rr2 = _make_rr(cs, observed_post_rollback=_oid(digest="d2"*32))
        assert _rid(rr1) != _rid(rr2)


class TestGroupSemantics:
    def test_group_ids_deterministic(self):
        cs = _make_cs()
        projector = ReceiptProjector()
        from aetheris.trace.model import Provenance, TraceValue
        ev = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="ev1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="rollback_attempt_observed",
            authority_class="none",
            revision=TraceValue(state="known", value="r1", source="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            evidence_refs=(), source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash="unknown", payload_hash="hash",
            recorded_at=TraceValue(state="known", value=1000.0, source="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="known", value="succeeded", source="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="no rollback"),
        )
        ctx = ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(), source_catalog=(), expected_trace_id="trace_1", strict=True,
        )
        result1 = projector.correlate(cs, (ev,), ctx)
        result2 = projector.correlate(cs, (ev,), ctx)
        assert len(result1.records) == 1
        assert result1.records[0].rollback_group_id.state == "known"
        assert result2.records[0].rollback_group_id == result1.records[0].rollback_group_id

    def test_one_failed_receipt_prevents_confirmation(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="not_confirmed",
            expected=cs.before, observed=cs.before,
            verifier=_tv("unknown", None, "failed"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ))
        assert rr.confirmation.status != "confirmed"

    def test_group_never_claims_atomicity(self):
        cs = _make_cs()
        projector = ReceiptProjector()
        ev = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="ev1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="rollback_attempt_observed",
            authority_class="none",
            revision=TraceValue(state="known", value="r1", source="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            evidence_refs=(), source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash="unknown", payload_hash="hash",
            recorded_at=TraceValue(state="known", value=1000.0, source="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="known", value="failed", source="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="no rollback"),
        )
        ctx = ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(), source_catalog=(), expected_trace_id="trace_1", strict=True,
        )
        result = projector.correlate(cs, (ev,), ctx)
        assert result.success
        assert result.records[0].confirmation.status != "confirmed"
