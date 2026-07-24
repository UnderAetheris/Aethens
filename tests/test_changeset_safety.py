"""Explicit safety-critical coverage for ChangeSet and RollbackReceipt.

Covers:
- restoration hash mismatch
- unsafe rollback rejection
- confirmation downgrade
- unknown propagation
- append-only preservation
- evidence preservation
- failed confirmation
- partial confirmation
- verifier mismatch
- forged receipt
- forged ChangeSet
- forged IDs
"""
from __future__ import annotations

from typing import Any

import pytest

from aetheris.changeset.canonical import canonical_hash, change_id, receipt_id
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
from aetheris.changeset.validate import (
    make_change_set,
    make_rollback_receipt,
    validate_change_set,
    validate_rollback_receipt,
)
from aetheris.trace.model import Provenance, TraceUnknown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tv(state: str, value: Any, reason: str = "test", source: str = "test") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason, source=source)
    raise ValueError(f"unknown state {state}")


def _oid(
    object_type: str = "file",
    scope: str = "repo",
    locator: Any = "src/a.py",
    digest: Any = "a" * 64,
    alg: str = "sha256",
    size: Any = 100,
    version: Any = "v1",
) -> ObjectIdentity:
    def _to_tv(v: Any) -> TraceValue:
        if isinstance(v, TraceValue):
            return v
        if v is None:
            return TraceValue(state="unknown", value=None, reason="not provided", source="test")
        return TraceValue(state="known", value=v, source="test")

    if locator is None and digest is None:
        return ObjectIdentity(
            object_type=object_type,
            scope=scope,
            locator=_tv("unknown", None, "absent"),
            hash_algorithm="unknown",
            digest=_tv("unknown", None, "absent"),
            size_bytes=_tv("unknown", None, "absent"),
            version_ref=_tv("unknown", None, "absent"),
        )
    return ObjectIdentity(
        object_type=object_type,
        scope=scope,
        locator=_to_tv(locator),
        hash_algorithm=alg,
        digest=_to_tv(digest),
        size_bytes=_to_tv(size),
        version_ref=_to_tv(version),
    )


def _make_cs(**overrides: Any) -> ChangeSet:
    base: dict[str, Any] = dict(
        schema_version=1,
        change_id="",
        trace_id=_tv("known", "trace_1"),
        task_id=_tv("known", "task_1"),
        session_id=_tv("unknown", None, "no session"),
        plan_id=_tv("unknown", None, "no plan"),
        capability_id="tools",
        owner_subsystem="tools",
        change_kind=ChangeKind.FILE_EDIT,
        disposition=MutationDisposition.REVERSIBLE,
        authority_class="execution",
        target=_oid("file", "repo", "src/main.py", "a" * 64, "sha256", 100, "v1"),
        before=_oid("file", "repo", "src/old.py", "b" * 64, "sha256", 100, "v0"),
        after=_oid("file", "repo", "src/new.py", "c" * 64, "sha256", 100, "v1"),
        inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="version_control",
            authority_boundary="sandbox_validation",
            target=_tv("known", {"commit": "abc123"}),
            preconditions=("independent_review",),
            expected_restore_identity=None,
            authorization_required=_tv("known", "commit_signer"),
        ),
        rollback_ref=_tv("unknown", None, "no rollback ref"),
        revision=_tv("known", "abc123sha"),
        config_fingerprint=_tv("unknown", None, "no config"),
        policy_fingerprint=_tv("unknown", None, "no policy"),
        evidence_refs=("evref_tools_v1",),
        source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(),
        observed_at=_tv("known", 1000.0),
    )
    base.update(overrides)
    return make_change_set(**base)


def _make_rr(cs: ChangeSet, **overrides: Any) -> ChangeSet:
    base: dict[str, Any] = dict(
        schema_version=1,
        receipt_id="",
        change_id=cs.change_id,
        trace_id=cs.trace_id,
        rollback_group_id=_tv("known", f"grp_{cs.change_id}"),
        sequence_index=0,
        parent_receipt_id=_tv("not_applicable", None, "first in group"),
        depends_on_receipt_ids=(),
        rollback_kind=RollbackKind.GIT_REVERT,
        rollback_target=cs.target,
        outcome=RollbackOutcome.SUCCEEDED,
        observed_pre_rollback=cs.after,
        observed_post_rollback=cs.before,
        confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ),
        revision=_tv("known", "r1"),
        config_fingerprint=_tv("unknown", None, "no config"),
        policy_fingerprint=_tv("unknown", None, "no policy"),
        evidence_refs=("evref_tools_v1",),
        source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(),
        attempted_at=_tv("known", 1000.0),
        confirmed_at=_tv("known", 1010.0),
    )
    base.update(overrides)
    return make_rollback_receipt(**base)


# ---------------------------------------------------------------------------
# 1. Restoration hash mismatch
# ---------------------------------------------------------------------------

class TestRestorationHashMismatch:
    def test_observed_post_rollback_mismatch_rejects_confirmed(self):
        cs = _make_cs()
        bad_after = _oid("file", "repo", "src/unknown.py", "f" * 64, "sha256", 100, "v?")
        rr = _make_rr(cs, observed_post_rollback=bad_after)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("observed_post_rollback.digest must match change_set.before.digest" in e for e in result.errors)

    def test_observed_pre_rollback_mismatch_rejects(self):
        cs = _make_cs()
        bad_pre = _oid("file", "repo", "src/unknown.py", "f" * 64, "sha256", 100, "v?")
        rr = _make_rr(cs, observed_pre_rollback=bad_pre)
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("observed_pre_rollback.digest must match change_set.after.digest" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 2. Unsafe rollback rejection
# ---------------------------------------------------------------------------

class TestUnsafeRollbackRejection:
    def test_wildcard_rollback_kind_in_inverse_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.UNKNOWN,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "x"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid
        assert any("unknown rollback kind" in e for e in result.errors)

    def test_append_only_requires_not_applicable_inverse(self):
        cs = _make_cs(
            change_kind=ChangeKind.RESEARCH_EVIDENCE_APPEND,
            disposition=MutationDisposition.APPEND_ONLY,
            before=_oid(),
            after=_oid(),
            inverse=InverseReference(
                kind=RollbackKind.GIT_REVERT,
                owner_subsystem="vc",
                authority_boundary=None,
                target=_tv("known", "x"),
                preconditions=(),
                expected_restore_identity=None,
                authorization_required=_tv("known", "y"),
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
                kind=RollbackKind.CONFIG_DISABLE,
                owner_subsystem="vc",
                authority_boundary=None,
                target=_tv("known", "x"),
                preconditions=(),
                expected_restore_identity=None,
                authorization_required=_tv("known", "y"),
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


# ---------------------------------------------------------------------------
# 3. Confirmation downgrade
# ---------------------------------------------------------------------------

class TestConfirmationDowngrade:
    def test_confirmed_requires_succeeded_outcome(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("confirmed restoration requires succeeded outcome" in e for e in result.errors)

    def test_confirmed_requires_known_verifier(self):
        cs = _make_cs()
        rr = _make_rr(cs, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("unknown", None, "no verifier"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("confirmed restoration requires known verifier provenance" in e for e in result.errors)

    def test_confirmed_cannot_have_mismatches(self):
        cs = _make_cs()
        rr = _make_rr(cs, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=("digest",),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("confirmed restoration cannot have mismatches" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 4. Unknown propagation
# ---------------------------------------------------------------------------

class TestUnknownPropagation:
    def test_missing_before_state_produces_unknown(self):
        from aetheris.changeset.projector import ChangeSetProjector, MutationEvidence
        from aetheris.trace.model import ReplayContext, SourceLocator, TraceEnvelope, TraceValue

        projector = ChangeSetProjector()
        env = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="ev1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="file_edit",
            authority_class="execution",
            revision=TraceValue(state="known", value="r1", source="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
            evidence_refs=(), source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash="unknown", payload_hash="hash",
            recorded_at=TraceValue(state="known", value=1000.0, source="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="known", value="file_edit", source="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="test"),
        )
        ctx = ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(), source_catalog=(), expected_trace_id="trace_1", strict=True,
        )
        result = projector.project(MutationEvidence(trace_events=(env,), before_object=None, after_object=None, context=ctx))
        assert result.success
        assert any(u.code == "missing_payload" for u in result.records[0].unknowns)

    def test_unknown_digest_remains_unknown(self):
        oid = _oid(digest=_tv("unknown", None, "not captured"), alg="unknown")
        assert oid.digest.state == "unknown"

    def test_trace_unknown_codes_are_standard(self):
        standard_codes = {
            "missing_revision", "missing_config", "missing_policy", "missing_evidence",
            "missing_trace_root", "missing_parent", "missing_cause", "missing_snapshot",
            "missing_payload", "missing_raw_bytes", "unsupported_record_version",
            "ambiguous_order", "redacted_secret", "external_input_not_recorded",
            "adapter_error", "hash_mismatch",
        }
        for code in standard_codes:
            u = TraceUnknown(code=code, field="x", reason="test", required_for=("test",))
            assert u.code == code


# ---------------------------------------------------------------------------
# 5. Append-only preservation
# ---------------------------------------------------------------------------

class TestAppendOnlyPreservation:
    def test_append_only_rejects_succeeded_rollback_claim(self):
        cs = _make_cs(
            change_kind=ChangeKind.JOURNAL_APPEND,
            disposition=MutationDisposition.APPEND_ONLY,
            inverse=InverseReference(
                kind=RollbackKind.NOT_APPLICABLE,
                owner_subsystem="memory",
                authority_boundary=None,
                target=_tv("not_applicable", None, "append-only"),
                preconditions=(),
                expected_restore_identity=None,
                authorization_required=_tv("not_applicable", None, "not applicable"),
            ),
        )
        rr = _make_rr(cs, outcome=RollbackOutcome.SUCCEEDED)
        result = validate_rollback_receipt(rr, cs)
        assert any("rollback reported success on append-only evidence" in w for w in result.warnings)

    def test_research_evidence_append_is_append_only_disposition(self):
        cs = _make_cs(
            change_kind=ChangeKind.RESEARCH_EVIDENCE_APPEND,
            disposition=MutationDisposition.APPEND_ONLY,
        )
        assert cs.disposition == MutationDisposition.APPEND_ONLY


# ---------------------------------------------------------------------------
# 6. Evidence preservation
# ---------------------------------------------------------------------------

class TestEvidencePreservation:
    def test_evidence_refs_survive_factory(self):
        refs = ("evref_tools_v1", "evref_config_v2")
        cs = _make_cs(evidence_refs=refs)
        assert cs.evidence_refs == refs

    def test_evidence_refs_survive_receipt_factory(self):
        cs = _make_cs()
        refs = ("evref_tools_v1",)
        rr = _make_rr(cs, evidence_refs=refs)
        assert rr.evidence_refs == refs

    def test_source_event_ids_preserved(self):
        event_ids = ("evt_1", "evt_2", "evt_3")
        cs = _make_cs(source_event_ids=event_ids)
        assert cs.source_event_ids == event_ids


# ---------------------------------------------------------------------------
# 7. Failed confirmation
# ---------------------------------------------------------------------------

class TestFailedConfirmation:
    def test_failed_outcome_cannot_claim_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid

    def test_failed_outcome_sets_not_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.FAILED, confirmation=RestorationConfirmation(
            status="not_confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("unknown", None, "rollback failed"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        assert rr.confirmation.status == "not_confirmed"


# ---------------------------------------------------------------------------
# 8. Partial confirmation
# ---------------------------------------------------------------------------

class TestPartialConfirmation:
    def test_partial_outcome_cannot_claim_exact_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.PARTIAL, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("succeeded outcome" in e for e in result.errors)

    def test_partial_outcome_can_claim_partially_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, outcome=RollbackOutcome.PARTIAL, confirmation=RestorationConfirmation(
            status="partially_confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("known", "persisted", "snapshot_provenance"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert result.valid


# ---------------------------------------------------------------------------
# 9. Verifier mismatch
# ---------------------------------------------------------------------------

class TestVerifierMismatch:
    def test_unknown_verifier_rejects_confirmed(self):
        cs = _make_cs()
        rr = _make_rr(cs, confirmation=RestorationConfirmation(
            status="confirmed",
            expected=cs.before,
            observed=cs.before,
            verifier=_tv("unknown", None, "no verification"),
            compared_fields=("object_type", "scope", "digest"),
            mismatches=(),
        ))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("known verifier provenance" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 10. Forged receipt
# ---------------------------------------------------------------------------

class TestForgedReceipt:
    def test_tampered_linkage_fails(self):
        cs = _make_cs()
        rr = _make_rr(cs, change_id="chg_forged")
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("does not match linked change_set" in e for e in result.errors)

    def test_wrong_target_scope_fails(self):
        cs = _make_cs()
        rr = _make_rr(cs, rollback_target=_oid("plan", "repo"))
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid


# ---------------------------------------------------------------------------
# 11. Forged ChangeSet
# ---------------------------------------------------------------------------

class TestForgedChangeSet:
    def test_change_id_derivation_detects_tampering(self):
        cs1 = _make_cs()
        cs2 = _make_cs(before=_oid(digest="d" + "1" * 63))
        assert cs1.change_id != cs2.change_id

    def test_factory_derives_correct_id(self):
        cs = _make_cs()
        expected = change_id(cs)
        assert cs.change_id == expected

    def test_invalid_change_id_rejected(self):
        cs = _make_cs()
        cs = ChangeSet(change_id="chg_invalid", **{
            f.name: getattr(cs, f.name) for f in ChangeSet.__dataclass_fields__.values()
            if f.name != "change_id"
        })
        result = validate_change_set(cs)
        assert not result.valid
        assert any("change_id does not match content" in e for e in result.errors)


# ---------------------------------------------------------------------------
# 12. Forged IDs
# ---------------------------------------------------------------------------

class TestForgedIDs:
    def test_deterministic_change_id(self):
        cs1 = _make_cs()
        cs2 = _make_cs()
        assert cs1.change_id == cs2.change_id
        assert cs1.change_id.startswith("chg_")

    def test_deterministic_receipt_id(self):
        cs = _make_cs()
        rr1 = _make_rr(cs)
        rr2 = _make_rr(cs)
        assert rr1.receipt_id == rr2.receipt_id
        assert rr1.receipt_id.startswith("rcpt_")

    def test_different_content_different_change_id(self):
        cs1 = _make_cs(before=_oid(digest="d" + "1" * 63))
        cs2 = _make_cs(before=_oid(digest="d" + "2" * 63))
        assert cs1.change_id != cs2.change_id

    def test_different_change_id_different_receipt_id(self):
        cs1 = _make_cs(capability_id="tools")
        cs2 = _make_cs(capability_id="config")
        rr1 = _make_rr(cs1)
        rr2 = _make_rr(cs2)
        assert rr1.receipt_id != rr2.receipt_id

    def test_canonical_hash_is_deterministic(self):
        cs = _make_cs()
        h1 = canonical_hash(cs)
        h2 = canonical_hash(cs)
        assert h1 == h2


# ---------------------------------------------------------------------------
# 13. Dangerous inverse references rejected
# ---------------------------------------------------------------------------

class TestDangerousInverseRejected:
    def test_disable_safety_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "disable_safety"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid
        assert any("dangerous pattern" in e for e in result.errors)

    def test_bypass_review_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "bypass_review"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid

    def test_expand_allowlist_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "expand_allowlist"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid

    def test_increase_budget_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "increase_budget"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid

    def test_delete_evidence_rejected(self):
        cs = _make_cs(inverse=InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "delete_evidence"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        ))
        result = validate_change_set(cs)
        assert not result.valid
