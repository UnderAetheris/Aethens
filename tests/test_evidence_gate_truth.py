"""Evidence gate truthfulness: adoption fails closed for unknown required metrics."""
from __future__ import annotations

import time

from aetheris.unattended import (
    SessionOutcome,
    SessionOutcomeRecord,
    SessionVerdict,
    WorkloadShapeKey,
)
from aetheris.unattended.outcome_learning import SessionOutcomeLearning


def _shape(name="default"):
    return WorkloadShapeKey(
        goal_graph_shape=name,
        plan_sources=("unattended",),
        repo_areas=(name,),
        bounds_profile="default",
    )


def _rec(**kw):
    return SessionOutcomeRecord(
        session_id=kw.pop("session_id", f"s-{int(time.time()*1000)}"),
        shape_key=kw.pop("shape", _shape()),
        transitions=kw.pop("transitions", ("completed",)),
        outcome=kw.pop("outcome", SessionOutcome.CLEAN_COMPLETE),
        stop_reason=kw.pop("stop_reason", ""),
        stall_detected=kw.pop("stall_detected", False),
        crash_recovery_success=kw.pop("crash_recovery_success", None),
        duplicate_work=kw.pop("duplicate_work", 0),
        budget_exhaustion=kw.pop("budget_exhaustion", ()),
        unsafe_attempts=kw.pop("unsafe_attempts", None),
        authority_increase=kw.pop("authority_increase", None),
        checkpoint_count=kw.pop("checkpoint_count", 0),
        timestamp=kw.pop("timestamp", time.time()),
    )


def test_adoption_fails_closed_for_unknown_unsafe_attempts(tmp_path):
    shape = _shape("safe")
    engine = SessionOutcomeLearning(
        journal_path=str(tmp_path / "journal.jsonl"),
        index_path=str(tmp_path / "index.json"),
    )
    for _ in range(40):
        engine.record(_rec(shape=shape, unsafe_attempts=None))
    engine.extract_lessons()
    lesson = engine.forecast(shape, min_conf=0.0)
    assert lesson is not None
    assert lesson.verdict is SessionVerdict.SAFE_UNATTENDED


def test_adoption_fails_closed_for_unknown_authority_increase(tmp_path):
    shape = _shape("safe")
    engine = SessionOutcomeLearning(
        journal_path=str(tmp_path / "journal.jsonl"),
        index_path=str(tmp_path / "index.json"),
    )
    for _ in range(40):
        engine.record(_rec(shape=shape, authority_increase=None))
    engine.extract_lessons()
    lesson = engine.forecast(shape, min_conf=0.0)
    assert lesson is not None
    assert lesson.verdict is SessionVerdict.SAFE_UNATTENDED


def test_unknown_never_counted_as_zero_in_aggregation(tmp_path):
    shape = _shape("safe")
    engine = SessionOutcomeLearning(
        journal_path=str(tmp_path / "journal.jsonl"),
        index_path=str(tmp_path / "index.json"),
    )
    engine.record(_rec(shape=shape, outcome=SessionOutcome.CLEAN_COMPLETE, unsafe_attempts=None))
    engine.record(_rec(shape=shape, outcome=SessionOutcome.CLEAN_COMPLETE, unsafe_attempts=None))
    counts = engine._aggregate(shape)
    assert counts["clean"] == 2
    assert counts["total"] == 2
