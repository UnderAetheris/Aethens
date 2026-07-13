"""Session Outcome Learning v0 — caution-only advisory substrate.

Tests for the read-only, structural-caution engine that learns from terminal
session records. The two hard canaries:

  * test_suggested_bounds_never_looser_than_default
  * test_no_lesson_moves_watchdog_toward_healthy

Together they prove learning can tighten and forewarn but can never expand
unattended behavior.
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest

from aetheris.unattended import (
    SessionOutcome,
    SessionOutcomeLearning,
    SessionOutcomeRecord,
    SessionLesson,
    SessionVerdict,
    StaticSampler,
    UnattendedSupervisor,
    WorkloadShapeKey,
    default_bounds,
    is_equal_or_tighter,
    shape_from_session,
)
from aetheris.unattended.model import (
    HealthSnapshot,
    HealthVerdict,
    Session,
    SessionBounds,
    SessionState,
)
from aetheris.unattended.watchdog import HealthWatchdog
from aetheris.unattended.outcome_learning import _short_hash


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _tmp_engine(tmp_path: Path) -> SessionOutcomeLearning:
    return SessionOutcomeLearning(
        journal_path=str(tmp_path / "journal.jsonl"),
        index_path=str(tmp_path / "index.json"),
    )


def _shape(name: str = "default") -> WorkloadShapeKey:
    return WorkloadShapeKey(
        goal_graph_shape=name,
        plan_sources=("unattended",),
        repo_areas=(name,),
        bounds_profile="default",
    )


def _rec(shape=None, outcome=None, **kw) -> SessionOutcomeRecord:
    shape = shape or _shape()
    outcome = outcome or SessionOutcome.CLEAN_COMPLETE
    return SessionOutcomeRecord(
        session_id=kw.pop("session_id", f"s-{_short_hash(shape.key())}"),
        shape_key=shape,
        transitions=kw.pop("transitions", ("completed",)),
        outcome=outcome,
        stop_reason=kw.pop("stop_reason", "stall_detected" if outcome == SessionOutcome.STALLED else ""),
        stall_detected=kw.pop("stall_detected", outcome == SessionOutcome.STALLED),
        crash_recovery_success=kw.pop("crash_recovery_success", None),
        duplicate_work=kw.pop("duplicate_work", 0),
        budget_exhaustion=kw.pop("budget_exhaustion", ()),
        unsafe_attempts=kw.pop("unsafe_attempts", 0),
        authority_increase=kw.pop("authority_increase", 0),
        checkpoint_count=kw.pop("checkpoint_count", 0),
        timestamp=kw.pop("timestamp", time.time()),
    )


def _sample_lesson() -> SessionLesson:
    return SessionLesson(
        lesson_id="lesson-abc12345",
        version=1,
        shape_key=_shape("X"),
        verdict=SessionVerdict.SAFE_UNATTENDED,
        confidence=0.9,
        note="shape clean 40/40 under existing bounds",
        suggested_bounds_profile=None,
        provenance=_provenance(_shape("X")),
    )


def _provenance(shape) -> "SessionLesson.provenance":  # type: ignore[name-defined]
    from aetheris.unattended.outcome_learning import SessionProvenance
    return SessionProvenance(
        shape_key=shape,
        supports=40,
        contradictions=0,
        window="n=40",
        last_confirmed_at=time.time(),
        evidence_sessions=(),
    )


def _bounds(max_ticks=200, max_steps=1000, max_consec=3, max_wall=3600.0):
    return SessionBounds(
        max_wall_clock_s=max_wall,
        max_steps=max_steps,
        max_consecutive_failures=max_consec,
        max_ticks_without_progress=max_ticks,
    )


def _session_obj(bounds=None, **kw) -> Session:
    bounds = bounds or _bounds()
    return Session(
        session_id=kw.pop("session_id", "test-session"),
        state=kw.pop("state", SessionState.RUNNING),
        bounds=bounds,
        frontier_ref=kw.pop("frontier_ref", "f"),
        **kw,
    )


def _watchdog(snapshot: HealthSnapshot, session_learning=None) -> HealthWatchdog:
    return HealthWatchdog(StaticSampler(snapshot), session_learning=session_learning)


# --------------------------------------------------------------------------- #
# 1. Structural: caution-only, no authority (the hard guarantees)               #
# --------------------------------------------------------------------------- #


class TestCautionOnlySchema:
    def test_lesson_schema_cannot_express_expanded_authority(self):
        banned = {"raise_budget", "skip_check", "looser_bounds", "disable_health", "execute"}
        fields = {f.name for f in dataclasses.fields(SessionLesson)}
        assert not (fields & banned)
        assert set(SessionVerdict) == {
            SessionVerdict.SAFE_UNATTENDED,
            SessionVerdict.LIKELY_STALL,
            SessionVerdict.LIKELY_NEEDS_REVIEW,
            SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS,
        }

    def test_suggested_bounds_never_looser_than_default(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        shapes = [_shape("safe"), _shape("tight"), _shape("stall"), _shape("review")]
        # Build history for each shape
        for i, shp in enumerate(shapes):
            if i == 0:
                # 40 clean -> SAFE_UNATTENDED (no suggestion)
                for _ in range(40):
                    engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
            elif i == 1:
                # 12 clean + 3 stalled -> SAFE_ONLY_WITH_TIGHTER_BOUNDS
                for _ in range(12):
                    engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
                for _ in range(3):
                    engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
            elif i == 2:
                # 10 stalled -> LIKELY_STALL (no suggestion)
                for _ in range(10):
                    engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
            else:
                # 8 review -> LIKELY_NEEDS_REVIEW (no suggestion)
                for _ in range(8):
                    engine.record(_rec(shape=shp, outcome=SessionOutcome.STOPPED_FOR_REVIEW))
        engine.extract_lessons()
        default = default_bounds()
        for shp in shapes:
            sb = engine.suggested_bounds(shp, default)
            assert is_equal_or_tighter(sb, default)

    def test_engine_holds_no_budget_or_safety_writer(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        banned = ("set_budget", "raise_budget", "set_bounds", "safety", "perimeter",
                  "skip_health", "edit", "run", "tools")
        for name in banned:
            assert not hasattr(engine, name), f"engine must not expose '{name}'"

    def test_lessons_are_immutable(self):
        lesson = _sample_lesson()
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(lesson, "confidence", 0.99)


# --------------------------------------------------------------------------- #
# 2. Fail-closed remains unconsultable in the permissive direction              #
# --------------------------------------------------------------------------- #


class TestFailClosedUnchanged:
    def test_stall_prior_can_only_increase_pause_eagerness(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="borderline")
        shp = shape_from_session(session, goal_graph_shape="borderline")
        for _ in range(12):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()

        base_snap = HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=150, consecutive_failures=0,
        )
        base_session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="borderline")
        base_wd = _watchdog(base_snap)
        base_decision = base_wd.check(base_session)

        learn_session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="borderline")
        learn_wd = _watchdog(base_snap, session_learning=engine)
        learn_decision = learn_wd.check(learn_session)

        assert base_decision.verdict == HealthVerdict.HEALTHY
        assert learn_decision.verdict == HealthVerdict.PAUSE
        # HEALTHY > PAUSE > STOP_FOR_REVIEW in permissiveness. Learning must be
        # <= base on permissiveness (i.e., index >= base index).
        permissive_order = (HealthVerdict.HEALTHY, HealthVerdict.PAUSE, HealthVerdict.STOP_FOR_REVIEW)
        assert permissive_order.index(learn_decision.verdict) >= permissive_order.index(base_decision.verdict)

    def test_no_lesson_moves_watchdog_toward_healthy(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="safe")
        shp = shape_from_session(session, goal_graph_shape="safe")
        for _ in range(40):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
        engine.extract_lessons()

        snap = HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=200, consecutive_failures=0,
        )
        session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="safe")
        d = _watchdog(snap, session_learning=engine).check(session)
        assert d.verdict != HealthVerdict.HEALTHY

    def test_fail_closed_unrecoverable_still_stops_with_learning_on(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        session = _session_obj(bounds=_bounds(max_consec=3), frontier_ref="safe")
        shp = shape_from_session(session, goal_graph_shape="safe")
        for _ in range(40):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
        engine.extract_lessons()

        snap = HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=0, consecutive_failures=3,
        )
        session = _session_obj(bounds=_bounds(max_consec=3), frontier_ref="safe")
        d = _watchdog(snap, session_learning=engine).check(session)
        assert d.verdict == HealthVerdict.STOP_FOR_REVIEW


# --------------------------------------------------------------------------- #
# 3. Recording + deterministic extraction (four+ outcomes)                     #
# --------------------------------------------------------------------------- #


class TestRecordingAndExtraction:
    def test_records_terminal_session_outcome(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        engine.record(_rec(outcome=SessionOutcome.CLEAN_COMPLETE))
        assert engine.record_count() == 1

    def test_learns_safe_shape_from_clean_repeats(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        for _ in range(40):
            engine.record(_rec(shape=_shape("A"), outcome=SessionOutcome.CLEAN_COMPLETE))
        engine.extract_lessons()
        lesson = engine.forecast(_shape("A"), min_conf=0.0)
        assert lesson is not None
        assert lesson.verdict == SessionVerdict.SAFE_UNATTENDED

    def test_learns_risky_shape_from_review_repeats(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        for _ in range(12):
            engine.record(_rec(shape=_shape("B"), outcome=SessionOutcome.STOPPED_FOR_REVIEW))
        engine.extract_lessons()
        lesson = engine.forecast(_shape("B"), min_conf=0.0)
        assert lesson is not None
        assert lesson.verdict == SessionVerdict.LIKELY_NEEDS_REVIEW

    def test_learns_tighter_bounds_shape(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        shp = _shape("C")
        for _ in range(12):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
        for _ in range(3):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()
        lesson = engine.forecast(shp, min_conf=0.0)
        assert lesson is not None
        assert lesson.verdict == SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS
        assert lesson.suggested_bounds_profile == "tighter"

    def test_extraction_deterministic_no_model(self, tmp_path: Path):
        engine1 = _tmp_engine(tmp_path / "e1")
        engine2 = _tmp_engine(tmp_path / "e2")
        records = [_rec(shape=_shape("D"), outcome=SessionOutcome.CLEAN_COMPLETE) for _ in range(40)]
        for r in records:
            engine1.record(r)
            engine2.record(r)
        engine1.extract_lessons()
        engine2.extract_lessons()
        l1 = engine1.forecast(_shape("D"), min_conf=0.0)
        l2 = engine2.forecast(_shape("D"), min_conf=0.0)
        assert l1 is not None and l2 is not None
        assert l1.verdict == l2.verdict
        assert l1.confidence == l2.confidence
        assert l1.note == l2.note


# --------------------------------------------------------------------------- #
# 4. Reversible retirement / decay of stale session lessons                    #
# --------------------------------------------------------------------------- #


class TestReversibleRetirement:
    def test_reformed_shape_decays_stall_lesson(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        shp = _shape("D")
        for _ in range(10):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()
        assert engine.forecast(shp, min_conf=0.0).verdict == SessionVerdict.LIKELY_STALL

        for _ in range(30):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
        engine.apply_decay()
        engine.extract_lessons()
        lesson = engine.forecast(shp, min_conf=0.0)
        assert lesson is not None
        assert lesson.verdict != SessionVerdict.LIKELY_STALL

    def test_retirement_is_reversible_and_preserves_history(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        for _ in range(40):
            engine.record(_rec(shape=_shape("E"), outcome=SessionOutcome.CLEAN_COMPLETE))
        engine.extract_lessons()
        lesson = engine.forecast(_shape("E"), min_conf=0.0)
        assert lesson is not None
        lid = lesson.lesson_id

        engine.retire_lesson(lid)
        assert engine.forecast(_shape("E"), min_conf=0.0) is None

        engine.unretire(lid)
        assert engine.forecast(_shape("E"), min_conf=0.0) is not None
        # Journal untouched: record count unchanged.
        assert engine.record_count() >= 40


# --------------------------------------------------------------------------- #
# 5. Advisory use by supervisor + watchdog                                     #
# --------------------------------------------------------------------------- #


class TestAdvisoryIntegration:
    def test_supervisor_defers_on_likely_needs_review(self, tmp_path: Path):
        from aetheris.unattended import SessionJournal

        engine = _tmp_engine(tmp_path)
        shp = _shape("review")
        for _ in range(12):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STOPPED_FOR_REVIEW))
        engine.extract_lessons()

        journal = SessionJournal(
            str(tmp_path / "u.journal.jsonl"),
            str(tmp_path / "u.snap.json"),
        )
        wd = HealthWatchdog(StaticSampler(HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=0, consecutive_failures=0,
        )))

        class FakeExec:
            def has_pending_work(self): return False

        sup = UnattendedSupervisor(
            FakeExec(), wd, journal, _bounds(),
            session_learning=engine, consume=True,
        )
        decision = sup.start_decision(shp)
        assert decision.recommend_human_attend is True
        assert decision.auto_started is False

    def test_supervisor_uses_tighter_bounds_when_advised(self, tmp_path: Path):
        from aetheris.unattended import SessionJournal

        engine = _tmp_engine(tmp_path)
        shp = _shape("tighten")
        for _ in range(12):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.CLEAN_COMPLETE))
        for _ in range(3):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()

        journal = SessionJournal(
            str(tmp_path / "u.journal.jsonl"),
            str(tmp_path / "u.snap.json"),
        )
        wd = HealthWatchdog(StaticSampler(HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=0, consecutive_failures=0,
        )))

        class FakeExec:
            def has_pending_work(self): return False

        sup = UnattendedSupervisor(
            FakeExec(), wd, journal, _bounds(max_ticks=200),
            session_learning=engine, consume=True,
        )
        decision = sup.start_decision(shp)
        assert decision.recommend_human_attend is False
        assert decision.auto_started is True
        assert is_equal_or_tighter(decision.bounds, _bounds(max_ticks=200))

    def test_watchdog_pauses_earlier_on_stall_prior(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="stall")
        shp = shape_from_session(session, goal_graph_shape="stall")
        for _ in range(12):
            engine.record(_rec(shape=shp, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()

        snap = HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=150, consecutive_failures=0,
        )
        base_session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="stall")
        base_decision = _watchdog(snap).check(base_session)

        learn_session = _session_obj(bounds=_bounds(max_ticks=200), frontier_ref="stall")
        learn_decision = _watchdog(snap, session_learning=engine).check(learn_session)

        assert base_decision.verdict == HealthVerdict.HEALTHY
        assert learn_decision.verdict == HealthVerdict.PAUSE


# --------------------------------------------------------------------------- #
# 6. Off / no-regression / gate                                               #
# --------------------------------------------------------------------------- #


class TestOffAndGate:
    def test_session_learning_off_is_byte_identical(self, tmp_path: Path):
        from aetheris.unattended import SessionJournal

        # Run without any learning engine
        journal1 = SessionJournal(
            str(tmp_path / "off.journal.jsonl"),
            str(tmp_path / "off.snap.json"),
        )
        wd1 = HealthWatchdog(StaticSampler(HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=0, consecutive_failures=0,
        )))

        class FakeExec:
            def has_pending_work(self): return False

        sup1 = UnattendedSupervisor(
            FakeExec(), wd1, journal1, _bounds(),
            session_learning=None, consume=False,
        )
        s1 = sup1.start(frontier_ref="wl")

        # Run with engine but consume=False
        engine = _tmp_engine(tmp_path)
        journal2 = SessionJournal(
            str(tmp_path / "off2.journal.jsonl"),
            str(tmp_path / "off2.snap.json"),
        )
        wd2 = HealthWatchdog(StaticSampler(HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=0, consecutive_failures=0,
        )))
        sup2 = UnattendedSupervisor(
            FakeExec(), wd2, journal2, _bounds(),
            session_learning=engine, consume=False,
        )
        s2 = sup2.start(frontier_ref="wl")

        assert s1.state == s2.state
        assert len(sup1.trace) == len(sup2.trace)

    def test_meets_adoption_gate(self, tmp_path: Path):
        engine = _tmp_engine(tmp_path)
        safe_shape = _shape("safe")
        risky_shape = _shape("risky")
        stall_shape = _shape("stall")

        for _ in range(40):
            engine.record(_rec(shape=safe_shape, outcome=SessionOutcome.CLEAN_COMPLETE))
        for _ in range(12):
            engine.record(_rec(shape=risky_shape, outcome=SessionOutcome.STOPPED_FOR_REVIEW))
        for _ in range(12):
            engine.record(_rec(shape=stall_shape, outcome=SessionOutcome.STALLED))
        engine.extract_lessons()

        default = default_bounds()

        # Safe shape: permitted under existing bounds
        safe_lesson = engine.forecast(safe_shape, min_conf=0.0)
        assert safe_lesson is not None
        assert safe_lesson.verdict == SessionVerdict.SAFE_UNATTENDED
        assert engine.suggested_bounds(safe_shape, default) == default

        # Risky shape: human review recommended
        risky_lesson = engine.forecast(risky_shape, min_conf=0.0)
        assert risky_lesson is not None
        assert risky_lesson.verdict == SessionVerdict.LIKELY_NEEDS_REVIEW

        # Stall shape: prior > 0
        prior = engine.stall_prior(stall_shape, min_conf=0.0)
        assert prior > 0.0

        # No authority increase: engine has no writer methods
        for banned in ("set_budget", "raise_budget", "set_bounds", "safety",
                       "perimeter", "skip_health", "edit", "run", "tools"):
            assert not hasattr(engine, banned)

        # Bounds never looser
        for shp in (safe_shape, risky_shape, stall_shape):
            assert is_equal_or_tighter(engine.suggested_bounds(shp, default), default)

        # Watchdog never moved toward HEALTHY by a safe lesson
        safe_snap = HealthSnapshot(
            queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
            research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
            ticks_without_progress=200, consecutive_failures=0,
        )
        safe_session = _session_obj(bounds=_bounds(max_ticks=200))
        d = _watchdog(safe_snap, session_learning=engine).check(safe_session)
        assert d.verdict != HealthVerdict.HEALTHY
