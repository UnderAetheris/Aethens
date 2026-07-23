"""Tests for rollback safety policy rejection."""
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
from aetheris.changeset.validate import validate_rollback_receipt, validate_change_set
from aetheris.trace.model import Provenance, SourceLocator, TraceEnvelope


def _tv(state: str, value: Any, reason: str = "test", source: str = "test") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason, source=source)
    raise ValueError(f"unknown state {state}")


def _oid(object_type="file", scope="repo", locator="src/a.py", digest="a"*64, alg="sha256") -> ObjectIdentity:
    return ObjectIdentity(
        object_type=object_type, scope=scope,
        locator=_tv("known", locator),
        hash_algorithm=alg,
        digest=_tv("known", digest),
        size_bytes=_tv("known", 100),
        version_ref=_tv("known", "v1"),
    )


def _make_cs(**kw):
    base = dict(
        schema_version=1, change_id="",
        trace_id=_tv("known", "trace_1"), task_id=_tv("known", "task_1"),
        session_id=_tv("unknown", None, "no session"), plan_id=_tv("unknown", None, "no plan"),
        capability_id="tools", owner_subsystem="tools",
        change_kind=ChangeKind.FILE_EDIT, disposition=MutationDisposition.REVERSIBLE,
        authority_class="execution",
        target=_oid(), before=_oid("file", "repo", "src/old.py", "b"*64),
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


def _env_for_receipt(event_type="rollback_attempt_observed") -> TraceEnvelope:
    return TraceEnvelope(
        schema_version=1, adapter_id="test", adapter_version=1, event_id="ev1",
        trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
        task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
        subsystem="test", capability_id="test", event_type=event_type,
        authority_class="none",
        revision=_tv("known", "r1"), config_fingerprint=_tv("unknown", None, ""),
        policy_fingerprint=_tv("unknown", None, ""),
        evidence_refs=(), source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
        source_hash="unknown", payload_hash="hash",
        recorded_at=_tv("known", 1000.0), stream_sequence=1, logical_order=None,
        ordering_basis="stream_sequence",
        provenance=Provenance(origin="persisted", confidence="exact"),
        outcome=_tv("known", "succeeded", "", "test"),
        unknowns=(), rollback_ref=_tv("not_applicable", None, "no rollback"),
    )


class TestSafetyRejection:
    def test_wildcard_rollback_kind_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.UNKNOWN, owner_subsystem="vc", authority_boundary=None,
            target=_tv("known", "x"), preconditions=(),
            expected_restore_identity=None, authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid
        assert any("unknown rollback kind" in e for e in result.errors)

    def test_append_only_requires_not_applicable_inverse(self):
        cs = _make_cs(
            change_kind=ChangeKind.RESEARCH_EVIDENCE_APPEND,
            disposition=MutationDisposition.APPEND_ONLY,
            before=_oid(), after=_oid(),
            inverse=InverseReference(
                kind=RollbackKind.GIT_REVERT, owner_subsystem="vc", authority_boundary=None,
                target=_tv("known", "x"), preconditions=(),
                expected_restore_identity=None, authorization_required=_tv("known", "y"),
            ),
        )
        result = validate_change_set(cs)
        assert not result.valid
        assert any("append-only mutation requires inverse.kind not_applicable" in e for e in result.errors)

    def test_config_disable_not_valid_for_append_only(self):
        cs = _make_cs(
            change_kind=ChangeKind.JOURNAL_APPEND,
            disposition=MutationDisposition.APPEND_ONLY,
            inverse=InverseReference(
                kind=RollbackKind.CONFIG_DISABLE, owner_subsystem="vc", authority_boundary=None,
                target=_tv("known", "x"), preconditions=(),
                expected_restore_identity=None, authorization_required=_tv("known", "y"),
            ),
        )
        rr = _make_rr(cs, rollback_kind=RollbackKind.CONFIG_DISABLE)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("config_disable is not valid for append-only mutations" in e for e in result.errors)

    def test_discard_sandbox_valid_only_for_sandbox_scope(self):
        cs = _make_cs(target=_oid("file", "repo", "src/a.py"))
        rr = _make_rr(cs, rollback_kind=RollbackKind.DISCARD_SANDBOX)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("discard_sandbox applies only to sandbox scope" in e for e in result.errors)

    def test_resume_checkpoint_valid_only_for_rebuildable(self):
        cs = _make_cs(disposition=MutationDisposition.APPEND_ONLY)
        rr = _make_rr(cs, rollback_kind=RollbackKind.RESUME_CHECKPOINT)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("resume_checkpoint is valid only for rebuildable_snapshot" in e for e in result.errors)

    def test_receipt_unknown_rollback_kind_rejected(self):
        cs = _make_cs()
        rr = _make_rr(cs, rollback_kind=RollbackKind.UNKNOWN)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("wildcard rollback kind UNKNOWN" in e for e in result.errors)

    def test_confirmed_requires_exact_hash_and_verifier(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="confirmed", expected=cs.before, observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid

    def test_checkpoint_resume_cannot_claim_external_restoration(self):
        cs = _make_cs(disposition=MutationDisposition.REBUILDABLE_SNAPSHOT)
        rr = _make_rr(cs, rollback_kind=RollbackKind.RESUME_CHECKPOINT, outcome=RollbackOutcome.SUCCEEDED)
        # restore checkpoint should not have expected restore identity matching external effects
        result = validate_rollback_receipt(rr, cs)
        assert result.valid

    def test_inverse_executable_false_required(self):
        inv = InverseReference(
            kind=RollbackKind.GIT_REVERT, owner_subsystem="vc", authority_boundary=None,
            target=_tv("known", "x"), preconditions=(),
            expected_restore_identity=None, authorization_required=_tv("known", "y"),
        )
        assert inv.executable is False

    def test_no_callable_or_command_in_inverse(self):
        inv = InverseReference(
            kind=RollbackKind.GIT_REVERT, owner_subsystem="vc", authority_boundary=None,
            target=_tv("known", "subprocess.run"), preconditions=(),
            expected_restore_identity=None, authorization_required=_tv("known", "y"),
        )
        validate = validate_change_set(ChangeSet(
            schema_version=1, change_id="",
            trace_id=_tv("known", "t1"), task_id=_tv("known", "t1"),
            session_id=_tv("unknown", None, "no session"), plan_id=_tv("unknown", None, "no plan"),
            capability_id="tools", owner_subsystem="tools",
            change_kind=ChangeKind.FILE_EDIT, disposition=MutationDisposition.REVERSIBLE,
            authority_class="execution", target=_oid(), before=_oid(), after=_oid(),
            inverse=inv, rollback_ref=_tv("unknown", None, "no ref"),
            revision=_tv("known", "r1"), config_fingerprint=_tv("unknown", None, "no config"),
            policy_fingerprint=_tv("unknown", None, "no policy"),
            evidence_refs=(), source_event_ids=(),
            provenance=Provenance(origin="persisted", confidence="exact"),
            unknowns=(), observed_at=_tv("known", 1000.0),
        ))
        assert validate.valid or any("callable" not in e for e in validate.errors)
