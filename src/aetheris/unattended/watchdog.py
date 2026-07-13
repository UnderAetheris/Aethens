"""Deterministic, fail-closed health watchdog.

Reads existing state (via an injected sampler) and returns a deterministic
`HealthVerdict`. Ambiguity resolves toward *less* activity:

    unrecoverable  -> STOP_FOR_REVIEW   (needs a human)
    recoverable     -> PAUSE              (checkpoint + wait)
    fully clean     -> HEALTHY           (ok to take one more gated step)

The watchdog mutates nothing. It holds no tool, no SafetyLayer, no writer,
no budget handle. It is a window onto health, not a control surface. Under
uncertainty it says pause; under an unrecoverable fault it says stop.

Session Outcome Learning may consult it read-only via a `session_learning`
object exposing `stall_prior(session) -> float`. The prior can ONLY shrink the
stall window (more eager to pause), never widen it or move a verdict toward
HEALTHY. With no consult (or a 0.0 prior) the watchdog is exactly Unattended v0.
"""
from __future__ import annotations

from typing import Callable

from .model import (
    HealthDecision,
    HealthSnapshot,
    HealthVerdict,
    Session,
    WatchdogThresholds,
    now,
)
from .outcome_learning import shape_from_session

Sampler = Callable[[Session], HealthSnapshot]


def _safe_stall_prior(session_learning, session: Session) -> float:
    """Call the consult's stall_prior, treating anything odd as 'no added caution'.

    Derives a WorkloadShapeKey from the session so the consult can look up the
    correct lesson. The prior is clamped to [0, 1]: a consult can only add
    pause-eagerness, never a negative (permission-to-continue) prior. Any error
    is treated as 0.0 so a broken consult can never loosen the watchdog.
    """
    try:
        shape = shape_from_session(session)
        prior = float(session_learning.stall_prior(shape))
    except Exception:
        return 0.0
    if prior < 0:
        return 0.0
    if prior > 1:
        return 1.0
    return prior


class HealthWatchdog:
    """Deterministic read of system health. Fail-closed: doubt -> pause."""

    def __init__(
        self,
        sampler: Sampler,
        thresholds: WatchdogThresholds | None = None,
        session_learning=None,
    ) -> None:
        self._sample = sampler
        self._thresholds = thresholds or WatchdogThresholds()
        # Optional read-only caution consult. If present, it must expose
        # ``stall_prior(session) -> float``. The prior can ONLY make the watchdog
        # MORE eager to pause (a non-negative number shrinks the stall window);
        # it can never delay a pause or move a verdict toward HEALTHY. When no
        # consult is wired, or it returns 0.0, behavior is exactly Unattended v0.
        self._session_learning = session_learning

    def check(self, session: Session) -> HealthDecision:
        s = self._sample(session)
        reasons: list[str] = []

        # ---- STOP_FOR_REVIEW (unrecoverable) ----
        if s.consecutive_failures >= session.bounds.max_consecutive_failures:
            reasons.append("repeated_identical_failures")
        if self._budget_exhausted_with_blocked_work(s):
            reasons.append("budget_exhausted_work_blocked")
        if s.perimeter_denials > 0 and self._perimeter_fault(s):
            reasons.append("perimeter_fault")
        if self._checkpoint_irreconcilable(session):
            reasons.append("checkpoint_irreconcilable")
        if reasons:
            return HealthDecision(HealthVerdict.STOP_FOR_REVIEW, tuple(reasons), s, now())

        # ---- PAUSE (recoverable concern) ----
        # Session learning may ONLY shrink this window (more eager to pause),
        # never widen it. A non-zero prior tightens the stall threshold; a zero
        # prior (or no consult) leaves it at the existing bound.
        tick_threshold = session.bounds.max_ticks_without_progress
        if self._session_learning is not None:
            prior = _safe_stall_prior(self._session_learning, session)
            if prior > 0:
                tick_threshold = max(
                    1, int(round((1.0 - prior) * session.bounds.max_ticks_without_progress))
                )
        if s.ticks_without_progress >= tick_threshold:
            reasons.append("stall_detected")
        if self._retry_or_repair_near_exhaustion(s):
            reasons.append("retry_repair_pressure")
        if self._budget_near_limit(s):
            reasons.append("budget_near_limit")
        if reasons:
            return HealthDecision(HealthVerdict.PAUSE, tuple(reasons), s, now())

        # ---- HEALTHY ----
        return HealthDecision(HealthVerdict.HEALTHY, (), s, now())

    # ------------------------------------------------------------------ #
    # Predicates (deterministic, read-only)                                #
    # ------------------------------------------------------------------ #

    def _budget_exhausted_with_blocked_work(self, s: HealthSnapshot) -> bool:
        exhausted = (
            s.retries_used >= self._thresholds.retry_limit
            or s.repairs_used >= self._thresholds.repair_limit
        )
        blocked = s.queue_depth > 0 or s.active_work > 0
        return exhausted and blocked

    def _retry_or_repair_near_exhaustion(self, s: HealthSnapshot) -> bool:
        return (
            s.retries_used >= self._thresholds.retry_limit - 1
            or s.repairs_used >= self._thresholds.repair_limit - 1
        )

    def _budget_near_limit(self, s: HealthSnapshot) -> bool:
        return (
            s.research_budget_used >= self._thresholds.budget_near
            or s.network_budget_used >= self._thresholds.budget_near
        )

    def _perimeter_fault(self, s: HealthSnapshot) -> bool:
        return s.perimeter_denials > self._thresholds.perimeter_denial_limit

    def _checkpoint_irreconcilable(self, session: Session) -> bool:
        return bool(getattr(session, "checkpoint_irreconcilable", False))
