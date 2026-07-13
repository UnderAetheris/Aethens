"""Health sampler: turns existing live state into a HealthSnapshot.

This is the *only* read the watchdog gets. It samples the existing queue,
the supervisor-tracked counters on the Session, and (best-effort) the
Research perimeter journal. It mutates nothing; it holds no handle to change
anything. The supervisor's authority is to halt, never to expand.
"""
from __future__ import annotations

from typing import Any, Callable

from ..controller.queue import TaskState
from .model import HealthSnapshot, Session

_ACTIVE_TASK = {TaskState.PLANNING, TaskState.EXECUTING}

Sampler = Callable[[Session], HealthSnapshot]


def build_sampler(executive, research: Any | None = None) -> Sampler:
    """Default sampler: read the existing queue + tracked counters.

    Research egress denials are read best-effort from the perimeter journal;
    egress budget enforcement already lives inside the NetworkPerimeter (fail-closed
    at the boundary). The supervisor adds no egress authority of its own.
    """
    journal = getattr(research, "_journal", None)

    def sampler(session: Session) -> HealthSnapshot:
        queue = getattr(executive, "_queue", None)
        if queue is not None:
            queue_depth = len(queue.pending())
            active_work = len(
                [r for r in queue.all() if r.state in _ACTIVE_TASK]
            )
        else:
            queue_depth = 0
            active_work = 0

        perimeter_denials = 0
        if journal is not None and hasattr(journal, "lines"):
            perimeter_denials = len(journal.lines("perimeter_denied"))

        return HealthSnapshot(
            queue_depth=queue_depth,
            active_work=active_work,
            retries_used=session.retries_used,
            repairs_used=session.repairs_used,
            research_budget_used=0.0,
            network_budget_used=0.0,
            perimeter_denials=perimeter_denials,
            ticks_without_progress=session.ticks_without_progress,
            consecutive_failures=session.consecutive_failures,
        )

    return sampler


class StaticSampler:
    """Test helper: return a fixed snapshot regardless of session."""

    def __init__(self, snapshot: HealthSnapshot) -> None:
        self._snapshot = snapshot

    def __call__(self, session: Session) -> HealthSnapshot:
        return self._snapshot
