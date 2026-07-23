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
