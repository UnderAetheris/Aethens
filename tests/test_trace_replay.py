"""Tests for trace replay engine."""
from __future__ import annotations


from aetheris.trace.model import (
    Provenance,
    ReplayContext,
    SourceLocator,
    TraceEnvelope,
    TraceValue,
)
from aetheris.trace.replay import ReplayEngine, _Edge, _topological_sort


def _make_env(event_id, parent=None, causes=(), unknowns=()) -> TraceEnvelope:
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
        subsystem="test",
        capability_id="test",
        event_type="test",
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
        env = _make_env("evt_1")
        state: dict = {}
        state = reduce_task_outcome(state, env)
        assert "tasks" in state
