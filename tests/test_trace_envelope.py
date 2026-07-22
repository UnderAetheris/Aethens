"""Tests for TraceEnvelope model, TraceValue, canonicalization, and identity."""
from __future__ import annotations


import pytest

from aetheris.trace.canonical import canonical_json, event_id, sha256_hex, sha256_str
from aetheris.trace.model import (
    Provenance,
    SourceLocator,
    TraceEnvelope,
    TraceValue,
)


class TestTraceValue:
    def test_known_requires_value_and_source(self):
        with pytest.raises(ValueError):
            TraceValue(state="known", value=None, source="src")
        with pytest.raises(ValueError):
            TraceValue(state="known", value="val", source=None)

    def test_unknown_requires_none_and_reason(self):
        with pytest.raises(ValueError):
            TraceValue(state="unknown", value="bad")
        tv = TraceValue(state="unknown", value=None, reason="missing")
        assert tv.value is None
        assert tv.reason == "missing"

    def test_not_applicable_requires_none_and_reason(self):
        tv = TraceValue(state="not_applicable", value=None, reason="N/A")
        assert tv.value is None

    def test_mismatch_requires_dict_and_reason(self):
        with pytest.raises(ValueError):
            TraceValue(state="mismatch", value="bad", reason="x")
        tv = TraceValue(state="mismatch", value={"expected": "a", "observed": "b"}, reason="diff")
        assert tv.value["expected"] == "a"


class TestCanonicalJson:
    def test_stable_across_key_order(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_json(a) == canonical_json(b)

    def test_unicode_stable(self):
        a = {"emoji": "hello \u2603"}
        assert canonical_json(a) == canonical_json(a)

    def test_nan_rejected(self):
        with pytest.raises(ValueError):
            canonical_json({"x": float("nan")})

    def test_infinity_rejected(self):
        with pytest.raises(ValueError):
            canonical_json({"x": float("inf")})


class TestHashing:
    def test_same_source_same_hash(self):
        raw = b'{"a": 1}'
        assert sha256_hex(raw) == sha256_hex(raw)

    def test_different_bytes_different_hash(self):
        assert sha256_hex(b"a") != sha256_hex(b"b")

    def test_payload_hash_differs_from_source_hash_when_formatted(self):
        raw = b'{"a": 1, "b": 2}'
        canonical = canonical_json({"b": 2, "a": 1})
        assert sha256_hex(raw) != sha256_str(canonical)

    def test_event_id_deterministic(self):
        eid1 = event_id(1, "adapter", 1, "stream", 1, "basis")
        eid2 = event_id(1, "adapter", 1, "stream", 1, "basis")
        assert eid1 == eid2
        assert eid1.startswith("evt_")

    def test_different_source_different_event_id(self):
        eid1 = event_id(1, "adapter", 1, "stream", 1, "basis_a")
        eid2 = event_id(1, "adapter", 1, "stream", 1, "basis_b")
        assert eid1 != eid2


class TestTraceEnvelope:
    def test_frozen_envelope_rejects_mutation(self):
        src = SourceLocator(store_kind="test", stream_id="test", path_hint="x")
        env = TraceEnvelope(
            schema_version=1,
            adapter_id="test",
            adapter_version=1,
            event_id="evt_abc",
            trace_id=None,
            parent_event_id=None,
            cause_event_ids=(),
            task_id=None,
            session_id=None,
            plan_id=None,
            goal_id=None,
            step_id=None,
            subsystem="test",
            capability_id="test",
            event_type="test",
            authority_class="none",
            revision=TraceValue(state="unknown", value=None, reason="x"),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="x"),
            policy_fingerprint=TraceValue(state="unknown", value=None, reason="x"),
            evidence_refs=(),
            source=src,
            source_hash="abc",
            payload_hash="def",
            recorded_at=TraceValue(state="unknown", value=None, reason="x"),
            stream_sequence=1,
            logical_order=None,
            ordering_basis="stream_sequence",
            provenance=Provenance(origin="persisted", confidence="exact"),
            outcome=TraceValue(state="not_applicable", value=None, reason="x"),
            unknowns=(),
            rollback_ref=TraceValue(state="not_applicable", value=None, reason="x"),
        )
        with pytest.raises(AttributeError):
            env.event_id = "new"
