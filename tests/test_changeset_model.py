"""Tests for ChangeSet and RollbackReceipt models, validation, and canonical IDs."""
from __future__ import annotations

from typing import Any

import pytest

from aetheris.changeset.canonical import canonical_hash, canonical_json
from aetheris.changeset.model import (
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
from aetheris.changeset.validate import (
    make_change_set,
    make_rollback_receipt,
    validate_change_set,
    validate_rollback_receipt,
)
from aetheris.trace.model import Provenance, TraceValue


def _tv(state: str, value: Any, reason: str = "", source: str = "test") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason)
    raise ValueError(f"unknown state {state}")


def _oid(
    object_type: str = "file",
    scope: str = "repo",
    locator: Any = "src/a.py",
    digest: Any = "a" * 64,
    alg: str = "sha256",
    size: Any = None,
    version: Any = None,
) -> ObjectIdentity:
    def _to_tv(v: Any) -> TraceValue:
        if isinstance(v, TraceValue):
            return v
        if v is None:
            return TraceValue(state="not_applicable", value=None, reason="not provided")
        return TraceValue(state="known", value=v, source="test")
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
        evidence_refs=(),
        source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(),
        observed_at=_tv("known", 1000.0),
    )
    base.update(overrides)
    return make_change_set(**base)


def _make_rr(cs: ChangeSet, **overrides: Any) -> RollbackReceipt:
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
        evidence_refs=(),
        source_event_ids=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(),
        attempted_at=_tv("known", 1000.0),
        confirmed_at=_tv("known", 1010.0),
    )
    base.update(overrides)
    return make_rollback_receipt(**base)


class TestChangeSetModel:
    def test_frozen(self):
        cs = _make_cs()
        with pytest.raises(AttributeError):
            cs.change_id = "other"

    def test_factory_derived_id_deterministic(self):
        cs1 = _make_cs()
        cs2 = _make_cs()
        assert cs1.change_id == cs2.change_id
        assert cs1.change_id.startswith("chg_")

    def test_different_content_different_id(self):
        cs1 = _make_cs(before=_oid(digest="d" + "1" * 63))
        cs2 = _make_cs(before=_oid(digest="d" + "2" * 63))
        assert cs1.change_id != cs2.change_id

    def test_known_sha256_digest_validates(self):
        good = "a" * 64
        bad = "a" * 63
        oid_good = _oid(digest=good)
        assert oid_good.digest.value == good
        with pytest.raises(ValueError):
            _oid(digest=bad)

    def test_unknown_digest_remains_unknown(self):
        oid = _oid(digest=_tv("unknown", None, "not captured"), alg="unknown")
        assert oid.digest.state == "unknown"

    def test_before_after_target_mismatch_fails(self):
        cs = _make_cs(before=_oid(object_type="plan", scope="repo"), after=_oid(object_type="file", scope="repo"))
        result = validate_change_set(cs)
        assert not result.valid
        assert any("before scope/type must match target" in e for e in result.errors)

    def test_create_delete_absence_representation(self):
        cs = _make_cs(
            before=_object_identity_absent("file", "repo"),
            after=_oid("file", "repo", "src/new.py", "c" * 64),
        )
        result = validate_change_set(cs)
        assert result.valid

    def test_unknown_change_kind_rejected(self):
        base: dict[str, Any] = dict(
            schema_version=1,
            change_id="chg_" + "a" * 32,
            trace_id=_tv("known", "trace_1"),
            task_id=_tv("known", "task_1"),
            session_id=_tv("unknown", None, "no session"),
            plan_id=_tv("unknown", None, "no plan"),
            capability_id="tools",
            owner_subsystem="tools",
            change_kind="other",
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
            evidence_refs=(),
            source_event_ids=(),
            provenance=Provenance(origin="persisted", confidence="exact"),
            unknowns=(),
            observed_at=_tv("known", 1000.0),
        )
        cs = ChangeSet(**base)
        result = validate_change_set(cs)
        assert not result.valid
        assert any("unknown change_kind" in e for e in result.errors)


def _object_identity_absent(object_type: str, scope: str) -> ObjectIdentity:
    return ObjectIdentity(
        object_type=object_type,
        scope=scope,
        locator=_tv("known", "absent"),
        hash_algorithm="not_applicable",
        digest=_tv("not_applicable", None, "object does not exist"),
        size_bytes=_tv("not_applicable", None, "object does not exist"),
        version_ref=_tv("not_applicable", None, "object does not exist"),
    )


class TestInverseReference:
    def test_executable_false_required(self):
        inv = InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "x"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        )
        assert inv.executable is False
        with pytest.raises(ValueError):
            InverseReference(
                kind=RollbackKind.GIT_REVERT,
                owner_subsystem="vc",
                authority_boundary=None,
                target=_tv("known", "x"),
                preconditions=(),
                expected_restore_identity=None,
                authorization_required=_tv("known", "y"),
                executable=True,
            )

    def test_no_callable_accepted(self):
        inv = InverseReference(
            kind=RollbackKind.GIT_REVERT,
            owner_subsystem="vc",
            authority_boundary=None,
            target=_tv("known", "x"),
            preconditions=(),
            expected_restore_identity=None,
            authorization_required=_tv("known", "y"),
        )
        assert not callable(inv.kind)
        assert not callable(inv.target)


class TestRollbackReceiptModel:
    def test_frozen(self):
        rr = _make_rr(_make_cs())
        with pytest.raises(AttributeError):
            rr.receipt_id = "other"

    def test_factory_derived_id_deterministic(self):
        cs = _make_cs()
        rr1 = _make_rr(cs)
        rr2 = _make_rr(cs)
        assert rr1.receipt_id == rr2.receipt_id
        assert rr1.receipt_id.startswith("rcpt_")

    def test_different_change_id_different_receipt_id(self):
        cs1 = _make_cs(capability_id="tools")
        cs2 = _make_cs(capability_id="config")
        rr1 = _make_rr(cs1)
        rr2 = _make_rr(cs2)
        assert rr1.receipt_id != rr2.receipt_id

    def test_confirmed_requires_exact_hash_and_verifier(self):
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

    def test_tampered_linkage_fails(self):
        cs = _make_cs()
        rr = _make_rr(cs, change_id="chg_forged")
        result = validate_rollback_receipt(rr, cs)
        assert not result.valid
        assert any("does not match linked change_set" in e for e in result.errors)


class TestChangeKindValues:
    def test_allowed_values(self):
        assert ChangeKind.FILE_EDIT == "file_edit"
        assert ChangeKind.RESEARCH_EVIDENCE_APPEND == "research_evidence_append"
        assert ChangeKind.UNKNOWN == "unknown"
        assert ChangeKind("file_edit") == ChangeKind.FILE_EDIT

    def test_no_other_wildcard(self):
        with pytest.raises(ValueError):
            ChangeKind("other")


class TestMutationDispositionValues:
    def test_allowed_values(self):
        assert MutationDisposition.REVERSIBLE == "reversible"
        assert MutationDisposition.APPEND_ONLY == "append_only"
        assert MutationDisposition.UNKNOWN == "unknown"


class TestRollbackKindValues:
    def test_allowed_values(self):
        assert RollbackKind.GIT_REVERT == "git_revert"
        assert RollbackKind.CONFIG_DISABLE == "config_disable"
        assert RollbackKind.NOT_APPLICABLE == "not_applicable"
        assert RollbackKind.UNKNOWN == "unknown"


class TestRollbackOutcomeValues:
    def test_allowed_values(self):
        assert RollbackOutcome.SUCCEEDED == "succeeded"
        assert RollbackOutcome.FAILED == "failed"
        assert RollbackOutcome.PARTIAL == "partial"
        assert RollbackOutcome.UNKNOWN == "unknown"


class TestCanonicalJson:
    def test_stable_across_key_order(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_json(a) == canonical_json(b)

    def test_deterministic_hash(self):
        cs = _make_cs()
        h1 = canonical_hash(cs)
        h2 = canonical_hash(cs)
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


class TestObjectIdentityValidationCollected:
    def test_invalid_sha256_digest_collected(self):
        bad_oid = ObjectIdentity(
            object_type="file", scope="repo",
            locator=_tv("known", "x"), hash_algorithm="sha256",
            digest=_tv("known", "short"), size_bytes=_tv("not_applicable", None, "test"),
            version_ref=_tv("not_applicable", None, "test"),
        )
        cs = _make_cs(target=bad_oid, before=_oid(), after=_oid())
        result = validate_change_set(cs)
        assert not result.valid
        assert any("sha256 digest must be exactly 64" in e for e in result.errors)

    def test_empty_object_type_collected(self):
        bad_oid = ObjectIdentity(
            object_type="", scope="repo",
            locator=_tv("known", "x"), hash_algorithm="unknown",
            digest=_tv("unknown", None, "test"), size_bytes=_tv("not_applicable", None, "test"),
            version_ref=_tv("not_applicable", None, "test"),
        )
        cs = _make_cs(target=bad_oid, before=_oid(), after=_oid())
        result = validate_change_set(cs)
        assert not result.valid
        assert any("object_type must be non-empty" in e for e in result.errors)


class TestCanonicalFactoriesFailExplicit:
    def test_make_change_set_does_not_swallow_exception(self):
        with pytest.raises(Exception):
            make_change_set(change_kind="not_a_change_kind")

    def test_make_rollback_receipt_does_not_swallow_exception(self):
        from aetheris.changeset.model import RollbackReceipt, RollbackOutcome, RestorationConfirmation
        with pytest.raises(Exception):
            make_rollback_receipt(outcome="not_an_outcome")

    def test_invalid_change_id_replaced_with_derived(self):
        cs = _make_cs()
        derived = change_id(cs)
        cs2 = ChangeSet(change_id="chg_invalid", **{
            f.name: getattr(cs, f.name) for f in ChangeSet.__dataclass_fields__.values()
            if f.name != "change_id"
        })
        result = validate_change_set(cs2)
        assert not result.valid
        assert any("does not match content" in e for e in result.errors)
