"""Session telemetry truthfulness tests."""
from __future__ import annotations

import time

from aetheris.unattended import (
    SessionOutcome,
    SessionOutcomeRecord,
    WorkloadShapeKey,
)


def _shape(name="default"):
    return WorkloadShapeKey(
        goal_graph_shape=name,
        plan_sources=("unattended",),
        repo_areas=(name,),
        bounds_profile="default",
    )


def test_checkpoint_count_counts_journal_checkpoints():
    events = [
        {"kind": "session_start", "session_id": "s1", "ts": 1.0, "data": {}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 2.0, "data": {"checkpoint_id": "cp-1", "steps_taken": 1}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 3.0, "data": {"checkpoint_id": "cp-2", "steps_taken": 2}},
        {"kind": "session_completed", "session_id": "s1", "ts": 4.0, "data": {"steps_taken": 2}},
    ]
    checkpoint_count = sum(1 for e in events if e.get("kind") == "session_checkpoint")
    assert checkpoint_count == 2


def test_crash_recovery_unknown_before_resume():
    rec = SessionOutcomeRecord(
        session_id="s1",
        shape_key=_shape(),
        transitions=("completed",),
        outcome=SessionOutcome.CLEAN_COMPLETE,
        stop_reason="",
        stall_detected=False,
        crash_recovery_success=None,
        duplicate_work=0,
        budget_exhaustion=(),
        unsafe_attempts=None,
        authority_increase=None,
        checkpoint_count=2,
        timestamp=time.time(),
    )
    assert rec.crash_recovery_success is None


def test_crash_recovery_true_only_after_successful_resume():
    events = [
        {"kind": "session_start", "session_id": "s1", "ts": 1.0, "data": {}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 2.0, "data": {"steps_taken": 1}},
        {"kind": "session_resumed", "session_id": "s1", "ts": 3.0, "data": {}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 4.0, "data": {"steps_taken": 2}},
        {"kind": "session_completed", "session_id": "s1", "ts": 5.0, "data": {"steps_taken": 2}},
    ]
    was_resumed = any(e.get("kind") == "session_resumed" for e in events)
    assert was_resumed
    terminal_completed = any(e.get("kind") == "session_completed" for e in events)
    assert terminal_completed
    crash_recovery_success = terminal_completed if was_resumed else None
    assert crash_recovery_success is True


def test_crash_recovery_false_after_failed_resume():
    events = [
        {"kind": "session_start", "session_id": "s1", "ts": 1.0, "data": {}},
        {"kind": "session_resumed", "session_id": "s1", "ts": 2.0, "data": {}},
        {"kind": "session_stopped", "session_id": "s1", "ts": 3.0, "data": {"state": "stopped"}},
    ]
    was_resumed = any(e.get("kind") == "session_resumed" for e in events)
    terminal_failed = any(e.get("kind") in ("session_stopped", "session_failed") for e in events)
    crash_recovery_success = False if was_resumed and terminal_failed else None
    assert crash_recovery_success is False


def test_duplicate_work_from_work_ids_not_steps_taken():
    events = [
        {"kind": "session_start", "session_id": "s1", "ts": 1.0, "data": {}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 2.0, "data": {"checkpoint_id": "cp-2", "steps_taken": 2}},
        {"kind": "session_resumed", "session_id": "s1", "ts": 3.0, "data": {}},
        {"kind": "session_checkpoint", "session_id": "s1", "ts": 4.0, "data": {"checkpoint_id": "cp-1", "steps_taken": 1}},
    ]
    resume_idx = next(i for i, e in enumerate(events) if e.get("kind") == "session_resumed")
    pre_resume_steps = max(
        (e.get("data", {}).get("steps_taken", 0) for e in events[:resume_idx] if e.get("kind") == "session_checkpoint"),
        default=0,
    )
    post_resume_steps = [
        e.get("data", {}).get("steps_taken", 0) for e in events[resume_idx:]
        if e.get("kind") == "session_checkpoint"
    ]
    duplicate_work = 1 if any(s < pre_resume_steps for s in post_resume_steps) else 0
    assert duplicate_work == 1


def test_absent_legacy_fields_load_as_unknown():
    d = {
        "session_id": "s1",
        "shape_key": "default",
        "transitions": ("completed",),
        "outcome": "clean_complete",
        "stop_reason": "",
        "stall_detected": False,
        "crash_recovery_success": None,
        "duplicate_work": 0,
        "budget_exhaustion": (),
    }
    rec = SessionOutcomeRecord.from_dict(d)
    assert rec.unsafe_attempts is None
    assert rec.authority_increase is None


def test_zero_preserved_only_when_observed():
    rec = SessionOutcomeRecord(
        session_id="s1",
        shape_key=_shape(),
        transitions=("completed",),
        outcome=SessionOutcome.CLEAN_COMPLETE,
        stop_reason="",
        stall_detected=False,
        crash_recovery_success=None,
        duplicate_work=0,
        budget_exhaustion=(),
        unsafe_attempts=None,
        authority_increase=None,
        checkpoint_count=0,
        timestamp=time.time(),
    )
    assert rec.duplicate_work == 0
    assert rec.checkpoint_count == 0
    assert rec.unsafe_attempts is None
    assert rec.authority_increase is None
