"""Tests for trace adapters."""
from __future__ import annotations



from aetheris.trace.adapters import (
    EvidenceAdapter,
    HierarchyAdapter,
    JsonlStoreAdapter,
    MemoryStoreAdapter,
    PlanStoreAdapter,
    ResearchJournalAdapter,
    UnattendedAdapter,
    adapter_for,
)
from aetheris.trace.model import (
    ReplayContext,
    SourceLocator,
    TraceValue,
)


def _ctx() -> ReplayContext:
    return ReplayContext(
        revision=TraceValue(state="unknown", value=None, reason="test"),
        config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
        policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
        evidence_catalog=(),
        source_catalog=(),
        strict=True,
    )


class TestMemoryStoreAdapter:
    def test_supports(self):
        assert MemoryStoreAdapter().supports(
            SourceLocator(store_kind="memory_store", stream_id="memory", path_hint="x")
        )
        assert not MemoryStoreAdapter().supports(
            SourceLocator(store_kind="jsonl_store", stream_id="x", path_hint="x")
        )

    def test_project_memory_record(self):
        loc = SourceLocator(store_kind="memory_store", stream_id="memory", path_hint="x", line_number=1)
        rec = {"ts": 123.0, "kind": "action_allowed", "data": {"tool": "ls"}}
        envs = MemoryStoreAdapter().project(loc, rec, _ctx())
        assert len(envs) == 1
        env = envs[0]
        assert env.subsystem == "memory"
        assert env.capability_id == "memory"
        assert env.event_type == "action_allowed"
        assert env.authority_class == "execution"
        assert env.stream_sequence == 1

    def test_malformed_record_returns_empty(self):
        envs = MemoryStoreAdapter().project(
            SourceLocator(store_kind="memory_store", stream_id="memory", path_hint="x"),
            "not_a_dict",
            _ctx(),
        )
        assert envs == ()


class TestJsonlStoreAdapter:
    def test_project_flat_record(self):
        loc = SourceLocator(store_kind="jsonl_store", stream_id="knowledge", path_hint="x", line_number=2)
        rec = {"kind": "knowledge_add", "text": "test", "tags": ["a"]}
        envs = JsonlStoreAdapter().project(loc, rec, _ctx())
        assert len(envs) == 1
        assert envs[0].subsystem == "memory"
        assert envs[0].capability_id == "memory"


class TestPlanStoreAdapter:
    def test_project_plan_sidecar(self):
        loc = SourceLocator(store_kind="plan_store", stream_id="plans", path_hint="x",
                           record_key="task-1", snapshot_version="1")
        rec = {"task_id": "task-1", "steps": [{"tool": "ls", "status": "pending"}], "created_at": 1.0}
        envs = PlanStoreAdapter().project(loc, rec, _ctx())
        assert len(envs) == 1
        assert envs[0].event_type == "plan_snapshot"
        assert envs[0].ordering_basis == "snapshot_version"


class TestResearchJournalAdapter:
    def test_network_egress_mapping(self):
        loc = SourceLocator(store_kind="research_journal", stream_id="research", path_hint="x", line_number=1)
        rec = {"kind": "perimeter_allowed", "url": "https://example.com"}
        envs = ResearchJournalAdapter().project(loc, rec, _ctx())
        assert envs[0].authority_class == "network_egress"

    def test_persistence_mapping(self):
        loc = SourceLocator(store_kind="research_journal", stream_id="research", path_hint="x", line_number=2)
        rec = {"kind": "bundle", "citations": [{"url": "x"}]}
        envs = ResearchJournalAdapter().project(loc, rec, _ctx())
        assert envs[0].authority_class == "persistence"


class TestHierarchyAdapter:
    def test_project_transition(self):
        loc = SourceLocator(store_kind="hierarchy_journal", stream_id="hierarchy", path_hint="x", line_number=1)
        rec = {"goal_id": "g1", "subgoal_id": "sg1", "to_state": "DONE"}
        envs = HierarchyAdapter().project(loc, rec, _ctx())
        assert len(envs) == 1
        assert envs[0].goal_id == "g1"
        assert envs[0].step_id == "sg1"


class TestUnattendedAdapter:
    def test_project_stopped(self):
        loc = SourceLocator(store_kind="unattended_journal", stream_id="unattended", path_hint="x", line_number=1)
        rec = {"kind": "session_stopped", "session_id": "s1", "data": {"state": "FAILED"}}
        envs = UnattendedAdapter().project(loc, rec, _ctx())
        assert envs[0].session_id == "s1"


class TestEvidenceAdapter:
    def test_project_evidence(self):
        loc = SourceLocator(store_kind="evidence_record", stream_id="evidence", path_hint="x")
        rec = {"capability_id": "safety", "gate": {"verdict": "stale"}}
        envs = EvidenceAdapter().project(loc, rec, _ctx())
        assert envs[0].capability_id == "safety"


class TestAdapterRegistry:
    def test_adapter_for_known_kinds(self):
        for kind in (
            "memory_store", "jsonl_store", "plan_store", "research_journal",
            "hierarchy_journal", "unattended_journal", "understanding_journal",
            "reliability_journal", "evidence_record", "skill_learning", "model_patch",
        ):
            loc = SourceLocator(store_kind=kind, stream_id="x", path_hint="x")
            assert adapter_for(loc) is not None

    def test_adapter_for_unknown_returns_none(self):
        loc = SourceLocator(store_kind="unknown_store", stream_id="x", path_hint="x")
        assert adapter_for(loc) is None
