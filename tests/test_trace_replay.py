"""Tests for trace replay engine — Phase 0 corrected."""
from __future__ import annotations

import hashlib
import os


from aetheris.trace.adapters import _base_envelope, _known_value
from aetheris.trace.model import (
    Provenance,
    ReplayContext,
    SourceLocator,
    TraceEnvelope,
    TraceUnknown,
    TraceValue,
)
from aetheris.trace.replay import ReplayEngine, _Edge, _topological_sort


def _make_env(event_id, parent=None, causes=(), unknowns=(), subsystem="test", event_type="test", capability_id="test") -> TraceEnvelope:
    return TraceEnvelope(
        schema_version=1,
        adapter_id="test",
        adapter_version=1,
        event_id=event_id,
        trace_id="trace_1",
        parent_event_id=parent,
        cause_event_ids=causes,
        task_id="t1",
        session_id=None,
        plan_id=None,
        goal_id=None,
        step_id=None,
        subsystem=subsystem,
        capability_id=capability_id,
        event_type=event_type,
        authority_class="none",
        revision=TraceValue(state="unknown", value=None, reason="test"),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
        policy_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
        evidence_refs=(),
        source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
        source_hash="abc",
        payload_hash="def",
        recorded_at=TraceValue(state="unknown", value=None, reason="test"),
        stream_sequence=1,
        logical_order=None,
        ordering_basis="stream_sequence",
        provenance=Provenance(origin="persisted", confidence="exact"),
        outcome=TraceValue(state="not_applicable", value=None, reason="test"),
        unknowns=unknowns,
        rollback_ref=TraceValue(state="not_applicable", value=None, reason="test"),
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


class TestTopologicalSort:
    def test_linear_order(self):
        order, cycle = _topological_sort(["a", "b", "c"], [_Edge("a", "b")])
        assert cycle is None
        assert order == ["a", "c", "b"]

    def test_cycle_detected(self):
        _, cycle = _topological_sort(["a", "b"], [_Edge("a", "b"), _Edge("b", "a")])
        assert cycle is not None


class TestReplayLevels:
    def test_empty_envelopes(self):
        engine = ReplayEngine()
        result = engine.replay([], _ctx())
        assert result.achieved_level >= 1
        assert result.status == "complete"

    def test_duplicate_event_id_fails(self):
        env = _make_env("evt_1")
        engine = ReplayEngine()
        result = engine.replay([env, env], _ctx())
        assert any(f.code == "malformed_record" for f in result.failures)

    def test_causal_cycle_invalid(self):
        env1 = _make_env("evt_1", parent="evt_2")
        env2 = _make_env("evt_2", parent="evt_1")
        engine = ReplayEngine()
        result = engine.replay([env1, env2], _ctx())
        assert result.status == "invalid"
        assert any(f.code == "causal_cycle" for f in result.failures)

    def test_deterministic_fingerprint(self):
        engine = ReplayEngine()
        env = _make_env("evt_1")
        r1 = engine.replay([env], _ctx())
        r2 = engine.replay([env], _ctx())
        assert r1.input_fingerprint == r2.input_fingerprint
        assert r1.result_fingerprint == r2.result_fingerprint

    def test_state_reconstruction(self):
        from aetheris.trace.replay import reduce_task_outcome
        env = _make_env("evt_1", subsystem="memory", event_type="action_allowed", capability_id="memory")
        state = {}
        state = reduce_task_outcome(state, env)
        assert "tasks" in state


class TestParentCauseValidation:
    def test_missing_parent_fails(self):
        env = _make_env("evt_1", parent="missing_parent")
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(f.code == "missing_parent" for f in result.failures)

    def test_missing_cause_fails(self):
        env = _make_env("evt_1", causes=("missing_cause",))
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(f.code == "missing_cause" for f in result.failures)

    def test_external_root_allowed(self):
        env = _make_env("evt_1", parent="root_trace")
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert not any(f.code == "missing_parent" for f in result.failures)


class TestHashValidation:
    def test_source_hash_from_raw_bytes(self):
        raw = b'{"kind":"test","data":{"task_id":"t1"}}'
        rec = {"kind": "test", "data": {"task_id": "t1"}, "_raw_bytes": raw}
        env = _base_envelope(
            adapter=type("X", (), {"adapter_id": "x", "adapter_version": 1})(),
            source=SourceLocator(store_kind="memory_store", stream_id="memory", path_hint="x"),
            record=rec,
            context=_ctx(),
            subsystem="memory", capability_id="memory", event_type="test",
            authority_class="none",
            outcome=_known_value("test", "test"),
        )
        assert env.source_hash == hashlib.sha256(raw).hexdigest()

    def test_missing_raw_bytes_unknown(self):
        rec = {"kind": "test", "data": {"task_id": "t1"}}
        env = _base_envelope(
            adapter=type("X", (), {"adapter_id": "x", "adapter_version": 1})(),
            source=SourceLocator(store_kind="memory_store", stream_id="memory", path_hint="x"),
            record=rec,
            context=_ctx(),
            subsystem="memory", capability_id="memory", event_type="test",
            authority_class="none",
            outcome=_known_value("test", "test"),
        )
        assert env.source_hash == "unknown"
        assert any(u.code == "missing_raw_bytes" for u in env.unknowns)


class TestReplayLevelsMax:
    def test_provenance_alone_does_not_grant_level_4(self):
        engine = ReplayEngine()
        env = _make_env("evt_1", subsystem="test", event_type="test")
        result = engine.replay([env], _ctx())
        assert result.achieved_level <= 3


class TestReducerRouting:
    def test_research_events_do_not_create_task_entries(self):
        engine = ReplayEngine()
        env = _make_env("evt_1", subsystem="research", event_type="fetch", capability_id="research")
        result = engine.replay([env], _ctx())
        assert "tasks" not in result.reconstructed_state or not result.reconstructed_state.get("tasks")

    def test_plan_events_do_not_create_tasks(self):
        engine = ReplayEngine()
        env = _make_env("evt_1", subsystem="planner", event_type="plan_snapshot", capability_id="planner")
        result = engine.replay([env], _ctx())
        assert "tasks" not in result.reconstructed_state or not result.reconstructed_state.get("tasks")


class TestUnknownHandling:
    def test_required_unknown_makes_replay_incomplete(self):
        unknowns = (TraceUnknown(code="missing_parent", field="task_id", reason="missing", required_for=("strict",)),)
        env = _make_env("evt_1", unknowns=unknowns)
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert result.achieved_level < 3


class TestFingerprintCanonical:
    def test_result_fingerprint_canonical_json(self):
        engine = ReplayEngine()
        env = _make_env("evt_1")
        result = engine.replay([env], _ctx())
        assert len(result.result_fingerprint) == 64


class TestTraceChangesetIsolation:
    def test_trace_core_has_no_changeset_import(self):
        trace_path = os.path.join(os.path.dirname(__file__), "..", "src", "aetheris", "trace")
        for root, _, files in os.walk(trace_path):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(root, f)
                text = open(path, "r", encoding="utf-8").read()
                assert "aetheris.changeset" not in text, f"trace module {path} imports changeset"


class TestHashVerificationInReplay:
    def test_source_hash_mismatch_fails(self):
        raw = b'{"kind":"test"}'
        env = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="evt_1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="test",
            authority_class="none",
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            evidence_refs=(),
            source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash="wrong_hash",
            payload_hash="def",
            recorded_at=TraceValue(state="unknown", value=None, reason="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="not_applicable", value=None, reason="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="test"),
            preserved_raw_bytes=raw,
            preserved_payload={"kind": "test"},
        )
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(f.code == "source_hash_mismatch" for f in result.failures)

    def test_payload_hash_mismatch_fails(self):
        env = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="evt_1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="test",
            authority_class="none",
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            evidence_refs=(),
            source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash="abc",
            payload_hash="wrong_payload_hash",
            recorded_at=TraceValue(state="unknown", value=None, reason="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="not_applicable", value=None, reason="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="test"),
            preserved_raw_bytes=None,
            preserved_payload={"kind": "test"},
        )
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(f.code == "payload_hash_mismatch" for f in result.failures)

    def test_source_and_payload_hash_not_interchangeable(self):
        raw = b'{"kind":"test"}'
        env = TraceEnvelope(
            schema_version=1, adapter_id="test", adapter_version=1, event_id="evt_1",
            trace_id="trace_1", parent_event_id=None, cause_event_ids=(),
            task_id="t1", session_id=None, plan_id=None, goal_id=None, step_id=None,
            subsystem="test", capability_id="test", event_type="test",
            authority_class="none",
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="test"),
            evidence_refs=(),
            source=SourceLocator(store_kind="test", stream_id="test", line_number=1),
            source_hash=hashlib.sha256(raw).hexdigest(),
            payload_hash="wrong_payload_hash",
            recorded_at=TraceValue(state="unknown", value=None, reason="test"),
            stream_sequence=1, logical_order=None, ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="not_applicable", value=None, reason="test"),
            unknowns=(), rollback_ref=TraceValue(state="not_applicable", value=None, reason="test"),
            preserved_raw_bytes=raw,
            preserved_payload={"kind": "test"},
        )
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(f.code == "payload_hash_mismatch" for f in result.failures)
        assert not any(f.code == "source_hash_mismatch" for f in result.failures)


class TestParentCauseOrderIndependent:
    def test_later_appearing_parent_not_missing(self):
        child = _make_env("child", parent="parent")
        parent = _make_env("parent")
        engine = ReplayEngine()
        result = engine.replay([child, parent], _ctx())
        assert not any(f.code == "missing_parent" for f in result.failures)

    def test_later_appearing_cause_not_missing(self):
        child = _make_env("child", causes=("cause",))
        cause = _make_env("cause")
        engine = ReplayEngine()
        result = engine.replay([child, cause], _ctx())
        assert not any(f.code == "missing_cause" for f in result.failures)


class TestStrictReplayUnknowns:
    def test_strict_replay_incomplete_with_required_unknowns(self):
        unknowns = (TraceUnknown(code="missing_revision", field="revision", reason="missing", required_for=("strict",)),)
        env = _make_env("evt_1", unknowns=unknowns)
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert result.status == "incomplete"
        assert result.achieved_level < 3

    def test_unknown_remains_unknown_in_strict_replay(self):
        unknowns = (TraceUnknown(code="missing_config", field="config", reason="missing", required_for=("strict",)),)
        env = _make_env("evt_1", unknowns=unknowns)
        engine = ReplayEngine()
        result = engine.replay([env], _ctx())
        assert any(u.code == "missing_config" for u in result.unknowns)
