"""Tests for ChangeSet and RollbackReceipt models, canonicalization, and trace adapters."""
from __future__ import annotations


import pytest

from aetheris.changeset.canonical import canonical_hash, canonical_json, change_id, receipt_id
from aetheris.changeset.model import ChangeKind, ChangeSet, RollbackKind, RollbackReceipt
from aetheris.changeset.view import ChangeSetView, RollbackReceiptView, render_rollback_receipt
from aetheris.trace.model import Provenance, TraceValue
from aetheris.trace.adapters import ChangeSetAdapter, RollbackReceiptAdapter
from aetheris.trace.replay import ReplayEngine


def _make_created_at() -> TraceValue:
    return TraceValue(state="known", value=1000.0, source="test")


def _make_revision() -> TraceValue:
    return TraceValue(state="known", value="abc123", source="test")


def _make_cs() -> ChangeSet:
    return ChangeSet(
        change_id="chg_test",
        trace_id="trace_1",
        task_id="task_1",
        session_id=None,
        plan_id=None,
        capability_id="tools",
        subsystem="tools",
        change_kind=ChangeKind.FILE_EDIT,
        before_hash="sha256:before",
        after_hash="sha256:after",
        before_ref=TraceValue(state="known", value={"path": "src/old.py"}, source="snapshot"),
        after_ref=TraceValue(state="known", value={"path": "src/new.py"}, source="snapshot"),
        inverse_operation="git_revert:HEAD~1",
        rollback_token="config: allowed_shell_commands=echo,ls,pwd,cat",
        revision=_make_revision(),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
        evidence_refs=("evref_tools_tool-registry-v0",),
        authority_class="execution",
        provenance=Provenance(origin="persisted", confidence="exact"),
        unknowns=(),
        created_at=_make_created_at(),
    )


def _make_rr() -> RollbackReceipt:
    return RollbackReceipt(
        receipt_id="rcpt_test",
        change_id="chg_test",
        rollback_kind=RollbackKind.GIT_REVERT,
        rollback_target=TraceValue(state="known", value={"commit": "abc123"}, source="git"),
        rollback_outcome=TraceValue(state="known", value="reverted", source="git"),
        confirmed_restored_state=TraceValue(state="known", value={"path": "src/old.py"}, source="snapshot"),
        unknowns=(),
        provenance=Provenance(origin="persisted", confidence="exact"),
        before_hash="sha256:before",
        after_hash="sha256:after",
        revision=_make_revision(),
        config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
        evidence_refs=(),
        created_at=_make_created_at(),
    )


class TestChangeSetModel:
    def test_change_set_creation(self):
        cs = _make_cs()
        assert cs.change_id == "chg_test"
        assert cs.capability_id == "tools"
        assert cs.change_kind == ChangeKind.FILE_EDIT

    def test_change_set_frozen(self):
        cs = _make_cs()
        with pytest.raises(AttributeError):
            cs.change_id = "new"

    def test_change_kind_values(self):
        assert ChangeKind.FILE_EDIT == "file_edit"
        assert ChangeKind.UNKNOWN == "unknown"


class TestRollbackReceiptModel:
    def test_receipt_creation(self):
        rr = _make_rr()
        assert rr.receipt_id == "rcpt_test"
        assert rr.change_id == "chg_test"
        assert rr.rollback_kind == RollbackKind.GIT_REVERT

    def test_rollback_kind_values(self):
        assert RollbackKind.GIT_REVERT == "git_revert"
        assert RollbackKind.NOT_APPLICABLE == "not_applicable"
        assert RollbackKind.UNKNOWN == "unknown"

    def test_receipt_frozen(self):
        rr = _make_rr()
        with pytest.raises(AttributeError):
            rr.receipt_id = "new"


class TestCanonicalJson:
    def test_stable_across_key_order(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert canonical_json(a) == canonical_json(b)

    def test_deterministic_hash(self):
        h1 = canonical_hash(_make_cs())
        h2 = canonical_hash(_make_cs())
        assert h1 == h2

    def test_different_inputs_different_hash(self):
        assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


class TestChangeIdDerivation:
    def test_deterministic(self):
        cs = _make_cs()
        id1 = change_id(cs)
        id2 = change_id(cs)
        assert id1 == id2
        assert id1.startswith("chg_")

    def test_different_before_hash(self):
        cs1 = ChangeSet(
            change_id="chg_test",
            trace_id="trace_1",
            task_id="task_1",
            session_id=None,
            plan_id=None,
            capability_id="tools",
            subsystem="tools",
            change_kind=ChangeKind.FILE_EDIT,
            before_hash="sha256:x",
            after_hash="sha256:after",
            before_ref=TraceValue(state="known", value={"path": "src/old.py"}, source="snapshot"),
            after_ref=TraceValue(state="known", value={"path": "src/new.py"}, source="snapshot"),
            inverse_operation="git_revert:HEAD~1",
            rollback_token="config: allowed_shell_commands=echo,ls,pwd,cat",
            revision=_make_revision(),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
            evidence_refs=("evref_tools_tool-registry-v0",),
            authority_class="execution",
            provenance=Provenance(origin="persisted", confidence="exact"),
            unknowns=(),
            created_at=_make_created_at(),
        )
        cs2 = ChangeSet(
            change_id="chg_test",
            trace_id="trace_1",
            task_id="task_1",
            session_id=None,
            plan_id=None,
            capability_id="tools",
            subsystem="tools",
            change_kind=ChangeKind.FILE_EDIT,
            before_hash="sha256:y",
            after_hash="sha256:after",
            before_ref=TraceValue(state="known", value={"path": "src/old.py"}, source="snapshot"),
            after_ref=TraceValue(state="known", value={"path": "src/new.py"}, source="snapshot"),
            inverse_operation="git_revert:HEAD~1",
            rollback_token="config: allowed_shell_commands=echo,ls,pwd,cat",
            revision=_make_revision(),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
            evidence_refs=("evref_tools_tool-registry-v0",),
            authority_class="execution",
            provenance=Provenance(origin="persisted", confidence="exact"),
            unknowns=(),
            created_at=_make_created_at(),
        )
        assert change_id(cs1) != change_id(cs2)


class TestReceiptIdDerivation:
    def test_deterministic(self):
        rr = _make_rr()
        id1 = receipt_id(rr)
        id2 = receipt_id(rr)
        assert id1 == id2
        assert id1.startswith("rcpt_")

    def test_different_change_id(self):
        rr1 = RollbackReceipt(
            receipt_id="rcpt_test",
            change_id="chg_a",
            rollback_kind=RollbackKind.GIT_REVERT,
            rollback_target=TraceValue(state="known", value={"commit": "abc"}, source="git"),
            rollback_outcome=TraceValue(state="known", value="reverted", source="git"),
            confirmed_restored_state=TraceValue(state="known", value={"path": "old.py"}, source="snapshot"),
            unknowns=(),
            provenance=Provenance(origin="persisted", confidence="exact"),
            before_hash="sha256:before",
            after_hash="sha256:after",
            revision=_make_revision(),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
            evidence_refs=(),
            created_at=_make_created_at(),
        )
        rr2 = RollbackReceipt(
            receipt_id="rcpt_test",
            change_id="chg_b",
            rollback_kind=RollbackKind.GIT_REVERT,
            rollback_target=TraceValue(state="known", value={"commit": "abc"}, source="git"),
            rollback_outcome=TraceValue(state="known", value="reverted", source="git"),
            confirmed_restored_state=TraceValue(state="known", value={"path": "old.py"}, source="snapshot"),
            unknowns=(),
            provenance=Provenance(origin="persisted", confidence="exact"),
            before_hash="sha256:before",
            after_hash="sha256:after",
            revision=_make_revision(),
            config_fingerprint=TraceValue(state="unknown", value=None, reason="no config", source="test"),
            evidence_refs=(),
            created_at=_make_created_at(),
        )
        assert receipt_id(rr1) != receipt_id(rr2)


class TestChangeSetView:
    def test_render_summary(self):
        cs = _make_cs()
        view = ChangeSetView(cs)
        text = view.summary()
        assert "change_id: chg_test" in text
        assert "tools" in text
        assert "file_edit" in text

    def test_to_dict(self):
        cs = _make_cs()
        view = ChangeSetView(cs)
        d = view.to_dict()
        assert d["change_id"] == "chg_test"
        assert d["capability_id"] == "tools"


class TestRollbackReceiptView:
    def test_render_summary(self):
        rr = _make_rr()
        text = render_rollback_receipt(rr)
        assert "receipt_id: rcpt_test" in text
        assert "git_revert" in text

    def test_view_summary(self):
        rr = _make_rr()
        view = RollbackReceiptView(rr)
        assert "change_id: chg_test" in view.summary()


class TestTraceAdapters:
    def test_changeset_adapter_supports(self):
        assert ChangeSetAdapter().supports(
            __import__("aetheris.trace.model", fromlist=["SourceLocator"]).SourceLocator(
                store_kind="change_set", stream_id="x", path_hint="x"
            )
        )

    def test_changeset_adapter_project(self):
        loc = __import__("aetheris.trace.model", fromlist=["SourceLocator"]).SourceLocator(
            store_kind="change_set", stream_id="x", path_hint="x"
        )
        rec = {
            "change_id": "chg_1",
            "trace_id": "trace_1",
            "capability_id": "tools",
            "subsystem": "tools",
            "change_kind": "file_edit",
            "before_hash": "sha256:before",
            "after_hash": "sha256:after",
            "before_ref": {"state": "known", "value": {"path": "old.py"}, "source": "snapshot"},
            "after_ref": {"state": "known", "value": {"path": "new.py"}, "source": "snapshot"},
            "inverse_operation": "git_revert:HEAD~1",
            "rollback_token": "config: allowed_shell_commands=echo,ls",
            "revision": {"state": "known", "value": "abc", "source": "test"},
            "config_fingerprint": {"state": "unknown", "value": None, "reason": "no config", "source": "test"},
            "evidence_refs": [],
            "authority_class": "execution",
            "provenance": {"origin": "persisted", "confidence": "exact"},
            "created_at": {"state": "known", "value": 1000.0, "source": "test"},
        }
        ctx = __import__("aetheris.trace.model", fromlist=["ReplayContext"]).ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(),
            source_catalog=(),
            expected_trace_id="trace_1",
            strict=True,
        )
        envs = ChangeSetAdapter().project(loc, rec, ctx)
        assert len(envs) == 1
        assert envs[0].event_type == "change_set"

    def test_rollback_receipt_adapter_project(self):
        loc = __import__("aetheris.trace.model", fromlist=["SourceLocator"]).SourceLocator(
            store_kind="rollback_receipt", stream_id="x", path_hint="x"
        )
        rec = {
            "receipt_id": "rcpt_1",
            "change_id": "chg_1",
            "rollback_kind": "git_revert",
            "rollback_target": {"state": "known", "value": {"commit": "abc"}, "source": "git"},
            "rollback_outcome": {"state": "known", "value": "reverted", "source": "git"},
            "confirmed_restored_state": {"state": "known", "value": {"path": "old.py"}, "source": "snapshot"},
            "provenance": {"origin": "persisted", "confidence": "exact"},
            "before_hash": "sha256:before",
            "after_hash": "sha256:after",
            "revision": {"state": "known", "value": "abc", "source": "test"},
            "config_fingerprint": {"state": "unknown", "value": None, "reason": "no config", "source": "test"},
            "evidence_refs": [],
            "created_at": {"state": "known", "value": 1000.0, "source": "test"},
        }
        ctx = __import__("aetheris.trace.model", fromlist=["ReplayContext"]).ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(),
            source_catalog=(),
            expected_trace_id="trace_1",
            strict=True,
        )
        envs = RollbackReceiptAdapter().project(loc, rec, ctx)
        assert len(envs) == 1
        assert envs[0].event_type == "rollback_receipt"


class TestReplayWithChangeset:
    def test_change_set_envelope_in_replay(self):
        from aetheris.trace.adapters import ChangeSetAdapter
        from aetheris.trace.model import ReplayContext, SourceLocator, TraceValue
        loc = SourceLocator(store_kind="change_set", stream_id="cs", path_hint="x", line_number=1)
        rec = {
            "change_id": "chg_1",
            "trace_id": "trace_1",
            "capability_id": "tools",
            "subsystem": "tools",
            "change_kind": "file_edit",
            "before_hash": "sha256:before",
            "after_hash": "sha256:after",
            "before_ref": {"state": "known", "value": {"path": "old.py"}, "source": "snapshot"},
            "after_ref": {"state": "known", "value": {"path": "new.py"}, "source": "snapshot"},
            "inverse_operation": "git_revert:HEAD~1",
            "rollback_token": "config: allowed_shell_commands=echo,ls",
            "revision": {"state": "known", "value": "abc", "source": "test"},
            "config_fingerprint": {"state": "unknown", "value": None, "reason": "no config", "source": "test"},
            "evidence_refs": [],
            "authority_class": "execution",
            "provenance": {"origin": "persisted", "confidence": "exact"},
            "created_at": {"state": "known", "value": 1000.0, "source": "test"},
        }
        ctx = ReplayContext(
            revision=TraceValue(state="unknown", value=None, reason="test"),
            config_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            policy_snapshot=TraceValue(state="unknown", value=None, reason="test"),
            evidence_catalog=(),
            source_catalog=(),
            expected_trace_id="trace_1",
            strict=True,
        )
        envs = ChangeSetAdapter().project(loc, rec, ctx)
        engine = ReplayEngine()
        result = engine.replay(list(envs), ctx)
        assert result.status == "complete"
        assert "change_kind_counts" in result.reconstructed_state
