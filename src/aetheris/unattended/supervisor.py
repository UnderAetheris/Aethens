"""Bounded, fail-closed Unattended Supervisor.

Drives the *existing* Executive in a bounded session. Holds NO tool, NO
SafetyLayer, NO plan mutator, NO budget writer, NO network. Its only powers
are `continue-one-gated-step`, `checkpoint`, and `pause/stop`. Continue routes
entirely through the existing gated spine (it calls `executive.step()`, which is
`run_once()`); checkpoint and pause/stop are the conservative directions.

It may stop work; it may never expand it. Bounds can only *stop sooner*; there
is no method that raises an existing budget. Under uncertainty it pauses; under
an unrecoverable fault it stops for human review; it never silently continues.
"""
from __future__ import annotations

import time
from typing import Any

from .model import (
    HealthVerdict,
    Session,
    SessionBounds,
    SessionState,
    make_session_id,
)
from .outcome_learning import (
    SessionOutcome,
    SessionOutcomeRecord,
    SessionVerdict,
    StartDecision,
    WorkloadShapeKey,
    shape_from_session,
)
from .watchdog import HealthWatchdog


class UnattendedSupervisor:
    """Bounded session supervisor. Composes, never bypasses, the Executive.

    Session Outcome Learning is an OPTIONAL, default-off read-only advisory. When
    ``session_learning`` is supplied AND ``consume`` is True, the supervisor may
    consult it before starting (defer a run that historically needs review, or
    use a tighter bounds profile) — but it can never expand authority. With no
    engine, or ``consume=False``, every start behaves byte-identically to
    Unattended v0. Outcome recording is a safe side-effect that never changes
    what the executive does.
    """

    def __init__(
        self,
        executive,
        watchdog: HealthWatchdog,
        journal,
        bounds: SessionBounds,
        *,
        session_learning=None,
        consume: bool = False,
        clock=time.time,
    ) -> None:
        self._executive = executive     # existing spine; supervisor holds no tool
        self._watchdog = watchdog
        self._journal = journal
        self._bounds = bounds
        self._session_learning = session_learning
        self._consume = consume
        self._clock = clock
        self.trace: list[dict[str, Any]] = []
        self._last_session: Session | None = None
        self._halt_requested: tuple[bool, str] = (False, "")
        self._pause_requested: bool = False

    # ------------------------------------------------------------------ #
    # Conservative human controls (brakes only)                            #
    # ------------------------------------------------------------------ #

    def request_stop(self, reason: str = "human_requested") -> None:
        """Brake: a human may halt a running session. Honored at next tick."""
        self._halt_requested = (True, reason)

    def request_pause(self, reason: str = "human_requested") -> None:
        """Brake: a human may pause a running session. Honored at next tick."""
        self._pause_requested = True

    def brake(self, session_id: str, *, pause: bool, reason: str = "human_requested") -> Session:
        """Conservative control for a paused/idle session: pause or stop it.

        This only ever *reduces* activity; it cannot force a step, raise a budget,
        or trigger egress. If the session is already terminal it is returned as-is.
        """
        session = self._journal.rehydrate(session_id)
        if session.is_terminal():
            return session
        if pause:
            return self._pause(session, reason=("human_pause", reason))
        return self._stop(session, reason=("human_stop", reason), failed=False)

    def status(self, session_id: str | None = None) -> dict[str, Any]:
        session = self._journal.rehydrate(session_id) if session_id \
            else self._last_session
        if session is None:
            return {"enabled": True, "active": False}
        return {
            "enabled": True,
            "active": not session.is_terminal(),
            "session_id": session.session_id,
            "state": session.state.value,
            "frontier_ref": session.frontier_ref,
            "steps_taken": session.steps_taken,
            "last_checkpoint": session.last_checkpoint,
            "stop_reason": session.stop_reason,
            "bounds": _bounds_to_dict(session.bounds),
            "recent": self._recent_decisions(5),
        }

    def _recent_decisions(self, n: int) -> list[dict[str, Any]]:
        return [
            e for e in reversed(self.trace)
            if e["kind"] == "health_decision"
        ][:n]

    # ------------------------------------------------------------------ #
    # Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def start(
        self,
        shape=None,
        frontier_ref: str = "default",
        session_id: str | None = None,
    ) -> Session:
        """Start a bounded session. `shape` (a WorkloadShapeKey) enables the
        caution-only advisory consult; when omitted it is derived from the
        frontier. With consumption off (or no engine) this is byte-identical to
        Unattended v0.
        """
        sid = session_id or make_session_id(frontier_ref)
        shape_key = shape if shape is not None else WorkloadShapeKey(
            goal_graph_shape=frontier_ref, plan_sources=("unattended",),
            repo_areas=(frontier_ref,), bounds_profile=_profile_name(self._bounds),
        )
        bounds = self._bounds
        deferred = False
        if self._consume and self._session_learning is not None:
            decision = self.start_decision(shape_key)
            if decision.recommend_human_attend:
                # Do NOT auto-start unattended. Defer for a human.
                deferred = True
            else:
                bounds = decision.bounds

        session = Session(
            session_id=sid,
            state=SessionState.STARTING,
            bounds=bounds,
            frontier_ref=frontier_ref,
            started_at=self._clock(),
        )
        self._journal.record_start(session)
        self._checkpoint(session)  # initial quiescent checkpoint
        if deferred:
            # Advisory decline: leave the run for a human; do not execute.
            session.state = SessionState.PAUSED
            session.stop_reason = "deferred: session learning advised human review"
            self._journal.record_paused(session)
            self._trace_event("deferred", {"reason": session.stop_reason})
            self._record_outcome(session)
            return session
        session.state = SessionState.RUNNING
        return self.run(session)

    def start_decision(self, shape) -> StartDecision:
        """Advisory consult. DATA only; the supervisor may ignore it.

        Never expands authority: the only non-default action it can recommend is
        to NOT auto-start (human attends) or to use a TIGHTER bounds profile.
        With no engine, or no confident lesson, it returns the default behavior.
        """
        default = StartDecision(
            shape_key=shape, lesson=None, recommend_human_attend=False,
            auto_started=True, bounds=self._bounds, note="no confident lesson",
        )
        if self._session_learning is None:
            return default
        lesson = self._session_learning.forecast(shape)
        if lesson is None:
            return default
        if lesson.verdict is SessionVerdict.LIKELY_NEEDS_REVIEW:
            return StartDecision(
                shape_key=shape, lesson=lesson, recommend_human_attend=True,
                auto_started=False, bounds=self._bounds,
                note="historically needed review; defer to human",
            )
        if lesson.verdict is SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS:
            bounds = self._session_learning.suggested_bounds(shape, self._bounds)
            return StartDecision(
                shape_key=shape, lesson=lesson, recommend_human_attend=False,
                auto_started=True, bounds=bounds, note="use tighter bounds",
            )
        # SAFE_UNATTENDED / LIKELY_STALL: permitted under existing bounds.
        return StartDecision(
            shape_key=shape, lesson=lesson, recommend_human_attend=False,
            auto_started=True, bounds=self._bounds, note="proceed under existing bounds",
        )

    def resume(self, session_id: str) -> Session:
        """Rehydrate from the journal + snapshot; skip completed work; continue."""
        session = self._journal.rehydrate(session_id)
        session.state = SessionState.RESUMED
        self._journal.record_resumed(session)
        self._trace_event("resumed", {"session_id": session_id})
        if session.checkpoint_irreconcilable:
            return self._stop(session, reason=("checkpoint_irreconcilable",), failed=True)
        return self.run(session)

    def run(self, session: Session) -> Session:
        if session.state in (
            SessionState.STARTING,
            SessionState.RESUMED,
            SessionState.PAUSED,
        ):
            session.state = SessionState.RUNNING
        if session.started_at == 0.0:
            session.started_at = self._clock()
        self._last_session = session

        # Hard backstop so a mis-configured world can never spin forever.
        safety_cap = max(session.bounds.max_steps * 10, 1000) + 100
        iterations = 0

        while not session.is_terminal():
            # Conservative human brakes are honored at the next tick.
            if self._halt_requested[0]:
                return self._stop(
                    session, reason=("human_stop", self._halt_requested[1]), failed=False
                )
            if self._pause_requested:
                self._pause_requested = False
                return self._pause(session, reason=("human_pause",))

            iterations += 1
            if iterations > safety_cap:
                return self._stop(
                    session, reason=("safety_cap_reached",), failed=False
                )

            decision = self._watchdog.check(session)
            self._journal.record_decision(
                session,
                decision.verdict.value,
                decision.reasons,
                _snapshot_to_dict(decision.snapshot),
            )
            self._trace_event(
                "health_decision",
                {"verdict": decision.verdict.value, "reasons": list(decision.reasons)},
            )

            if decision.verdict is HealthVerdict.STOP_FOR_REVIEW:
                return self._stop(session, reason=decision.reasons, failed=True)
            if decision.verdict is HealthVerdict.PAUSE:
                self._checkpoint(session)
                return self._pause(session, reason=decision.reasons)
            if self._session_bounds_reached(session):
                self._checkpoint(session)
                return self._stop(
                    session, reason=("session_bound_reached",), failed=False
                )
            if not self._work_ready(session):
                self._checkpoint(session)
                return self._complete(session)

            # HEALTHY + bounded + work ready -> take exactly ONE existing gated
            # step through the unchanged spine. No tool, no SafetyLayer, no writer.
            tick = self._executive.step()
            self._apply_tick_outcome(session, tick)
            session.steps_taken += 1
            if self._at_safe_point(session):
                self._checkpoint(session)

        return session

    # ------------------------------------------------------------------ #
    # Terminal transitions (all conservative: stop / pause / complete)      #
    # ------------------------------------------------------------------ #

    def _pause(self, session: Session, reason) -> Session:
        session.state = SessionState.PAUSED
        session.stop_reason = _join(reason)
        self._journal.record_paused(session)
        self._trace_event("paused", {"reason": session.stop_reason})
        self._record_outcome(session)
        return session

    def _stop(self, session: Session, reason, *, failed: bool) -> Session:
        session.state = SessionState.FAILED if failed else SessionState.STOPPED
        session.stop_reason = _join(reason)
        self._journal.record_stopped(session)
        self._trace_event(
            "stopped", {"reason": session.stop_reason, "failed": failed}
        )
        self._record_outcome(session)
        return session

    def _complete(self, session: Session) -> Session:
        session.state = SessionState.COMPLETED
        self._journal.record_completed(session)
        self._trace_event("completed", {})
        self._record_outcome(session)
        return session

    # ------------------------------------------------------------------ #
    # Outcome recording (safe side-effect; never changes the run)         #
    # ------------------------------------------------------------------ #

    def _record_outcome(self, session: Session) -> None:
        """Append a terminal session outcome to the session-learning journal.

        Pure side-effect: a crash-safe, provenance-stamped record. It reads only;
        it cannot change the executive's steps, bounds, or authority. With no
        engine wired this is a no-op. Metrics are derived from observed journal
        evidence; absent evidence is recorded as None, never fabricated as zero.
        """
        if self._session_learning is None:
            return
        paused = session.state is SessionState.PAUSED
        stalled = "stall" in session.stop_reason
        if session.state is SessionState.FAILED:
            outcome = SessionOutcome.FAILED
        elif session.state is SessionState.STOPPED:
            outcome = SessionOutcome.STOPPED_FOR_REVIEW
        elif stalled and paused:
            outcome = SessionOutcome.STALLED
        elif paused:
            outcome = SessionOutcome.PAUSED_RECOVERED
        else:
            outcome = SessionOutcome.CLEAN_COMPLETE

        events = self._journal.get_events(session.session_id)
        was_resumed = any(e.get("kind") == "session_resumed" for e in events)
        if was_resumed:
            crash_recovery_success = session.state is SessionState.COMPLETED
        else:
            crash_recovery_success = None

        checkpoint_count = sum(1 for e in events if e.get("kind") == "session_checkpoint")

        duplicate_work = 0
        if was_resumed:
            resume_idx = next(i for i, e in enumerate(events) if e.get("kind") == "session_resumed")
            pre_resume_steps = max(
                (e.get("data", {}).get("steps_taken", 0) for e in events[:resume_idx] if e.get("kind") == "session_checkpoint"),
                default=0,
            )
            post_resume_steps = [
                e.get("data", {}).get("steps_taken", 0) for e in events[resume_idx:]
                if e.get("kind") == "session_checkpoint"
            ]
            if any(s < pre_resume_steps for s in post_resume_steps):
                duplicate_work = 1

        rec = SessionOutcomeRecord(
            session_id=session.session_id,
            shape_key=shape_from_session(session),
            transitions=(session.state.value,),
            outcome=outcome,
            stop_reason=session.stop_reason,
            stall_detected=stalled,
            crash_recovery_success=crash_recovery_success,
            duplicate_work=duplicate_work,
            budget_exhaustion=("budget",) if "budget" in session.stop_reason else (),
            unsafe_attempts=None,
            authority_increase=None,
            checkpoint_count=checkpoint_count,
            timestamp=self._clock(),
        )
        self._session_learning.record(rec)

    # ------------------------------------------------------------------ #
    # Guards (read-only; never expand authority)                           #
    # ------------------------------------------------------------------ #

    def _session_bounds_reached(self, session: Session) -> bool:
        elapsed = self._clock() - session.started_at
        over_wall = elapsed >= session.bounds.max_wall_clock_s
        over_steps = session.steps_taken >= session.bounds.max_steps
        return over_wall or over_steps

    def _work_ready(self, session: Session) -> bool:
        return self._executive.has_pending_work()

    def _at_safe_point(self, session: Session) -> bool:
        # executive.step() returns only after the gated spine completes; the
        # supervisor never checkpoints mid-write. Quiescent by construction.
        return True

    def _checkpoint(self, session: Session) -> None:
        cp_id = f"cp-{session.steps_taken}"
        self._journal.checkpoint(session, cp_id)
        self._trace_event(
            "checkpoint", {"checkpoint_id": cp_id, "steps_taken": session.steps_taken}
        )

    # ------------------------------------------------------------------ #
    # Health-counter maintenance (observed from step outcomes)            #
    # ------------------------------------------------------------------ #

    def _apply_tick_outcome(self, session: Session, tick: Any) -> None:
        o = getattr(tick, "outcome", None)
        if o == "repair_inserted":
            session.repairs_used += 1
            session.ticks_without_progress += 1
        elif o == "retrying":
            session.retries_used += 1
            session.consecutive_failures += 1
            session.ticks_without_progress += 1
        elif o in ("failed", "blocked", "waiting_for_context"):
            session.consecutive_failures += 1
            session.ticks_without_progress += 1
        elif o in ("done", "step_done", "plan_review"):
            session.retries_used = 0
            session.consecutive_failures = 0
            session.ticks_without_progress = 0

    def _trace_event(self, kind: str, data: dict[str, Any]) -> None:
        self.trace.append({"kind": kind, "ts": self._clock(), **data})


def _join(reason) -> str:
    if isinstance(reason, (tuple, list)):
        return "; ".join(str(r) for r in reason)
    return str(reason)


def _snapshot_to_dict(s) -> dict[str, Any]:
    return {
        "queue_depth": s.queue_depth,
        "active_work": s.active_work,
        "retries_used": s.retries_used,
        "repairs_used": s.repairs_used,
        "research_budget_used": s.research_budget_used,
        "network_budget_used": s.network_budget_used,
        "perimeter_denials": s.perimeter_denials,
        "ticks_without_progress": s.ticks_without_progress,
        "consecutive_failures": s.consecutive_failures,
    }


def _bounds_to_dict(b) -> dict[str, Any]:
    return {
        "max_wall_clock_s": b.max_wall_clock_s,
        "max_steps": b.max_steps,
        "max_consecutive_failures": b.max_consecutive_failures,
        "max_ticks_without_progress": b.max_ticks_without_progress,
    }


def _profile_name(bounds: SessionBounds) -> str:
    return f"steps={bounds.max_steps};ticks={bounds.max_ticks_without_progress}"
