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
from .watchdog import HealthWatchdog


class UnattendedSupervisor:
    """Bounded session supervisor. Composes, never bypasses, the Executive."""

    def __init__(
        self,
        executive,
        watchdog: HealthWatchdog,
        journal,
        bounds: SessionBounds,
        *,
        clock=time.time,
    ) -> None:
        self._executive = executive     # existing spine; supervisor holds no tool
        self._watchdog = watchdog
        self._journal = journal
        self._bounds = bounds
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
        self, frontier_ref: str = "default", session_id: str | None = None
    ) -> Session:
        sid = session_id or make_session_id(frontier_ref)
        session = Session(
            session_id=sid,
            state=SessionState.STARTING,
            bounds=self._bounds,
            frontier_ref=frontier_ref,
            started_at=self._clock(),
        )
        self._journal.record_start(session)
        self._checkpoint(session)  # initial quiescent checkpoint
        session.state = SessionState.RUNNING
        return self.run(session)

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
        return session

    def _stop(self, session: Session, reason, *, failed: bool) -> Session:
        session.state = SessionState.FAILED if failed else SessionState.STOPPED
        session.stop_reason = _join(reason)
        self._journal.record_stopped(session)
        self._trace_event(
            "stopped", {"reason": session.stop_reason, "failed": failed}
        )
        return session

    def _complete(self, session: Session) -> Session:
        session.state = SessionState.COMPLETED
        self._journal.record_completed(session)
        self._trace_event("completed", {})
        return session

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
