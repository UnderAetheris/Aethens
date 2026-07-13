"""Deterministic, fail-closed health watchdog.

Reads existing state (via an injected sampler) and returns a deterministic
`HealthVerdict`. Ambiguity resolves toward *less* activity:

    unrecoverable  -> STOP_FOR_REVIEW   (needs a human)
    recoverable     -> PAUSE              (checkpoint + wait)
    fully clean     -> HEALTHY           (ok to take one more gated step)

The watchdog mutates nothing. It holds no tool, no SafetyLayer, no writer,
no budget handle. It is a window onto health, not a control surface. Under
uncertainty it says pause; under an unrecoverable fault it says stop.
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

Sampler = Callable[[Session], HealthSnapshot]


class HealthWatchdog:
    """Deterministic read of system health. Fail-closed: doubt -> pause."""

    def __init__(
        self,
        sampler: Sampler,
        thresholds: WatchdogThresholds | None = None,
    ) -> None:
        self._sample = sampler
        self._thresholds = thresholds or WatchdogThresholds()

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
        if s.ticks_without_progress >= session.bounds.max_ticks_without_progress:
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
