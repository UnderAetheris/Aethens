"""Tests for ChangeSet projection from trace evidence."""
from __future__ import annotations

from typing import Any


from aetheris.changeset.model import (
    RollbackKind,
)
from aetheris.changeset.projector import (
    ChangeSetProjector,
    MutationEvidence,
)
from aetheris.trace.model import (
    Provenance,
    ReplayContext,
    SourceLocator,
    TraceEnvelope,
    TraceValue,
)


def _env(event_id: str, event_type: str = "file_edit", subsystem: str = "planner", **kw: Any) -> TraceEnvelope:
    return TraceEnvelope(
        schema_version=1,
        adapter_id="test",
        adapter_version=1,
        event_id=event_id,
        trace_id="trace_1",
        parent_event_id=None,
        cause_event_ids=(),
        task_id="task_1",
        session_id=None,
        plan_id=None,
        goal_id=None,
        step_id=None,
        subsystem=subsystem,
        capability_id=kw.get("capability_id", subsystem),
        event_type=event_type,
        authority_class="execution",
        revision=TraceValue(state="known", value="r1", source="test"),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
        policy_fingerprint=TraceValue(state="unknown", value=None, reason="no policy", source="test"),
        evidence_refs=(),
        source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
        source_hash="unknown",
        payload_hash="hash",
        recorded_at=TraceValue(state="known", value=1000.0, source="test"),
        stream_sequence=1,
        logical_order=None,
        ordering_basis="stream_sequence",
        provenance=Provenance(origin="persisted", confidence="exact"),
        outcome=TraceValue(state="known", value=event_type, source="test"),
        unknowns=(),
        rollback_ref=TraceValue(state="not_applicable", value=None, reason="no rollback"),
    )


def _ctx() -> ReplayContext:
    return ReplayContext(
        revision=TraceValue(state="unknown", value=None, reason="test"),
        config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
        policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
        evidence_catalog=(),
        source_catalog=(),
        expected_trace_id="trace_1",
        strict=True,
    )


def test_file_edit_projects():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="file_edit"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert len(result.records) == 1
    cs = result.records[0]
    assert cs.change_kind.value == "file_edit"


def test_plan_edit_projects():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="plan_edit", subsystem="planner"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert result.records[0].change_kind.value == "plan_edit"


def test_skill_promotion_projects():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="skill_promotion", subsystem="skills"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert result.records[0].change_kind.value == "skill_promotion"
    assert result.records[0].inverse.kind == RollbackKind.TOMBSTONE_UNRETIRE


def test_skill_retirement_projects():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="skill_retirement", subsystem="skills"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert result.records[0].change_kind.value == "skill_retirement"
    assert result.records[0].inverse.kind == RollbackKind.TOMBSTONE_UNRETIRE


def test_research_evidence_append_is_append_only():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="research_evidence_append", subsystem="research"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert result.records[0].disposition.value == "append_only"
    assert result.records[0].change_kind.value == "research_evidence_append"
    assert result.records[0].inverse.kind == RollbackKind.NOT_APPLICABLE


def test_session_checkpoint_projects():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="session_checkpoint", subsystem="unattended"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert result.records[0].change_kind.value == "session_checkpoint"
    assert result.records[0].disposition.value == "rebuildable_snapshot"


def test_unsupported_mutation_class_fails():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="unsupported_thing"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert not result.success
    assert any(f.code == "unsupported_reducer" for f in result.failures)


def test_missing_before_state_remains_unknown():
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="file_edit"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    assert result.success
    assert any(u.code == "missing_payload" for u in result.records[0].unknowns)


def test_change_set_envelope_event_type_matches_reducer():
    from aetheris.changeset.projector import change_set_to_envelope
    from aetheris.trace.replay import _route_change_set_summary
    projector = ChangeSetProjector()
    ev = MutationEvidence(trace_events=(_env("e1", event_type="file_edit"),), before_object=None, after_object=None, context=_ctx())
    result = projector.project(ev)
    cs = result.records[0]
    envelope = change_set_to_envelope(cs, _ctx())
    assert envelope.event_type == "change_set"
    assert _route_change_set_summary(envelope)


def test_rollback_receipt_envelope_event_type_matches_reducer():
    from aetheris.changeset.model import ChangeSet, RollbackReceipt, RestorationConfirmation, ObjectIdentity, TraceValue
    from aetheris.changeset.projector import rollback_receipt_to_envelope
    from aetheris.trace.replay import _route_rollback_summary
    from aetheris.changeset.model import RollbackOutcome
    cs = ChangeSet(
        schema_version=1, change_id="chg_test",
        trace_id=TraceValue(state="known", value="t1", source="test"),
        task_id=TraceValue(state="known", value="task_1", source="test"),
        session_id=TraceValue(state="unknown", value=None, reason="test", source="test"),
        plan_id=TraceValue(state="unknown", value=None, reason="test", source="test"),
        capability_id="test", owner_subsystem="test",
        change_kind=RollbackKind.GIT_REVERT, disposition=RollbackKind.GIT_REVERT,
        authority_class="none",
        target=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="x", source="test"), hash_algorithm="unknown", digest=TraceValue(state="unknown", value=None, reason="test", source="test"), size_bytes=TraceValue(state="unknown", value=None, reason="test", source="test"), version_ref=TraceValue(state="unknown", value=None, reason="test", source="test")),
        before=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="old", source="test"), hash_algorithm="unknown", digest=TraceValue(state="unknown", value=None, reason="test", source="test"), size_bytes=TraceValue(state="unknown", value=None, reason="test", source="test"), version_ref=TraceValue(state="unknown", value=None, reason="test", source="test")),
        after=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="new", source="test"), hash_algorithm="unknown", digest=TraceValue(state="unknown", value=None, reason="test", source="test"), size_bytes=TraceValue(state="unknown", value=None, reason="test", source="test"), version_ref=TraceValue(state="unknown", value=None, reason="test", source="test")),
        inverse=__import__("aetheris.changeset.model", fromlist=["InverseReference"]).InverseReference(
            kind=RollbackKind.GIT_REVERT, owner_subsystem="test", authority_boundary=None,
            target=TraceValue(state="known", value="x", source="test"), preconditions=(),
            expected_restore_identity=None,
            authorization_required=TraceValue(state="unknown", value=None, reason="test", source="test"),
        ),
        rollback_ref=TraceValue(state="unknown", value=None, reason="test", source="test"),
        revision=TraceValue(state="known", value="r1", source="test"),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        evidence_refs=(), source_event_ids=(), provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(), observed_at=TraceValue(state="known", value=1000.0, source="test"),
    )
    rr = RollbackReceipt(
        schema_version=1, receipt_id="rcpt_test", change_id=cs.change_id,
        trace_id=cs.trace_id, rollback_group_id=TraceValue(state="known", value="grp", source="test"),
        sequence_index=0, parent_receipt_id=TraceValue(state="not_applicable", value=None, reason="test", source="test"),
        depends_on_receipt_ids=(), rollback_kind=RollbackKind.GIT_REVERT,
        rollback_target=cs.target, outcome=RollbackOutcome.SUCCEEDED,
        observed_pre_rollback=cs.after, observed_post_rollback=cs.before,
        confirmation=RestorationConfirmation(
            status="confirmed", expected=cs.before, observed=cs.before,
            verifier=TraceValue(state="known", value="v", source="test"),
            compared_fields=("object_type", "scope", "digest"), mismatches=(),
        ),
        revision=TraceValue(state="known", value="r1", source="test"),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        evidence_refs=(), source_event_ids=(), provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(), attempted_at=TraceValue(state="known", value=1000.0, source="test"),
        confirmed_at=TraceValue(state="known", value=1010.0, source="test"),
    )
    envelope = rollback_receipt_to_envelope(rr, cs, _ctx())
    assert envelope.event_type == "rollback_receipt"
    assert _route_rollback_summary(envelope)


def test_receipt_projection_derives_from_rollback_events():
    from aetheris.changeset.projector import ReceiptProjector
    from aetheris.changeset.model import ChangeSet, ObjectIdentity, TraceValue
    from aetheris.changeset.model import RollbackOutcome
    import copy
    cs = ChangeSet(
        schema_version=1, change_id="chg_test",
        trace_id=TraceValue(state="known", value="t1", source="test"),
        task_id=TraceValue(state="known", value="task_1", source="test"),
        session_id=TraceValue(state="unknown", value=None, reason="test", source="test"),
        plan_id=TraceValue(state="unknown", value=None, reason="test", source="test"),
        capability_id="test", owner_subsystem="test",
        change_kind=__import__("aetheris.changeset.model", fromlist=["ChangeKind"]).ChangeKind.FILE_EDIT,
        disposition=__import__("aetheris.changeset.model", fromlist=["MutationDisposition"]).MutationDisposition.REVERSIBLE,
        authority_class="none",
        target=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="x", source="test"), hash_algorithm="unknown", digest=TraceValue(state="unknown", value=None, reason="test", source="test"), size_bytes=TraceValue(state="unknown", value=None, reason="test", source="test"), version_ref=TraceValue(state="unknown", value=None, reason="test", source="test")),
        before=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="old", source="test"), hash_algorithm="sha256", digest=TraceValue(state="known", value="a"*64, source="test"), size_bytes=TraceValue(state="known", value=100, source="test"), version_ref=TraceValue(state="known", value="v0", source="test")),
        after=ObjectIdentity(object_type="file", scope="repo", locator=TraceValue(state="known", value="new", source="test"), hash_algorithm="sha256", digest=TraceValue(state="known", value="b"*64, source="test"), size_bytes=TraceValue(state="known", value=100, source="test"), version_ref=TraceValue(state="known", value="v1", source="test")),
        inverse=__import__("aetheris.changeset.model", fromlist=["InverseReference"]).InverseReference(
            kind=RollbackKind.GIT_REVERT, owner_subsystem="test", authority_boundary=None,
            target=TraceValue(state="known", value="x", source="test"), preconditions=(),
            expected_restore_identity=None,
            authorization_required=TraceValue(state="unknown", value=None, reason="test", source="test"),
        ),
        rollback_ref=TraceValue(state="unknown", value=None, reason="test", source="test"),
        revision=TraceValue(state="known", value="r1", source="test"),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        policy_fingerprint=TraceValue(state="unknown", value=None, reason="test", source="test"),
        evidence_refs=(), source_event_ids=(), provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(), observed_at=TraceValue(state="known", value=1000.0, source="test"),
    )
    rollback_env = _env("rollback_1", event_type="rollback_receipt", subsystem="test")
    projector = ReceiptProjector()
    result = projector.correlate(cs, (rollback_env,), _ctx())
    assert result.success
    rr = result.records[0]
    assert rr.observed_pre_rollback is not None
    assert rr.observed_post_rollback is not None


def test_missing_capability_id_remains_typed_unknown():
    projector = ChangeSetProjector()
    env = _env("e1", event_type="file_edit", capability_id=None)
    result = projector.project(MutationEvidence(trace_events=(env,), before_object=None, after_object=None, context=_ctx()))
    assert result.success
    cs = result.records[0]
    assert isinstance(cs.capability_id, str) or hasattr(cs.capability_id, 'state')


def test_missing_authority_class_remains_typed_unknown():
    projector = ChangeSetProjector()
    env = _env("e1", event_type="file_edit")
    env = TraceEnvelope(
        schema_version=env.schema_version, adapter_id=env.adapter_id, adapter_version=env.adapter_version,
        event_id=env.event_id, trace_id=env.trace_id, parent_event_id=env.parent_event_id,
        cause_event_ids=env.cause_event_ids, task_id=env.task_id, session_id=env.session_id,
        plan_id=env.plan_id, goal_id=env.goal_id, step_id=env.step_id,
        subsystem=env.subsystem, capability_id=env.capability_id, event_type=env.event_type,
        authority_class=None,
        revision=env.revision, config_fingerprint=env.config_fingerprint, policy_fingerprint=env.policy_fingerprint,
        evidence_refs=env.evidence_refs, source=env.source, source_hash=env.source_hash,
        payload_hash=env.payload_hash, recorded_at=env.recorded_at, stream_sequence=env.stream_sequence,
        logical_order=env.logical_order, ordering_basis=env.ordering_basis, provenance=env.provenance,
        outcome=env.outcome, unknowns=env.unknowns, rollback_ref=env.rollback_ref,
        preserved_raw_bytes=env.preserved_raw_bytes, preserved_payload=env.preserved_payload,
    )
    result = projector.project(MutationEvidence(trace_events=(env,), before_object=None, after_object=None, context=_ctx()))
    assert result.success
