"""Data model for the Unattended Run Loop & Health Watchdog.

Pure data + enums. No tool, no SafetyLayer, no budget writer, no network.
The supervisor that uses these types may stop work; it may never expand it.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum


def now() -> float:
    return time.time()


class SessionState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"          # health check said stop; recoverable; awaiting resume/review
    RESUMED = "resumed"
    COMPLETED = "completed"    # frontier fully done
    STOPPED = "stopped"        # halted with a reason (may need human review)
    FAILED = "failed"          # unrecoverable fault; awaiting human review


class HealthVerdict(str, Enum):
    HEALTHY = "healthy"                 # ok to take one more gated step
    PAUSE = "pause"                     # recoverable concern; checkpoint + wait
    STOP_FOR_REVIEW = "stop_for_review" # unrecoverable / needs a human


@dataclass(frozen=True)
class SessionBounds:
    max_wall_clock_s: float
    max_steps: int
    max_consecutive_failures: int
    max_ticks_without_progress: int
    # NOTE: these can only STOP sooner; there is no field that raises an existing
    # budget (retry/repair/promotion/retirement/research/network). The supervisor
    # adds brakes only; it never widens a throttle. Verified by canary.


@dataclass(frozen=True)
class HealthSnapshot:
    """Deterministic read of existing state at a tick. DATA; drives pause/stop only."""
    queue_depth: int
    active_work: int
    retries_used: int
    repairs_used: int
    research_budget_used: float
    network_budget_used: float
    perimeter_denials: int
    ticks_without_progress: int
    consecutive_failures: int


@dataclass(frozen=True)
class HealthDecision:
    verdict: HealthVerdict
    reasons: tuple[str, ...]           # which predicates fired, explainable
    snapshot: HealthSnapshot
    timestamp: float


@dataclass
class Session:
    session_id: str                    # STABLE, content/frontier-derived
    state: SessionState
    bounds: SessionBounds
    frontier_ref: str                  # the task/goal frontier this session drives
    last_checkpoint: str | None = None  # id of last confirmed quiescent checkpoint
    stop_reason: str = ""
    steps_taken: int = 0

    # --- observed health counters (persisted so resume continues faithfully) ---
    retries_used: int = 0
    repairs_used: int = 0
    ticks_without_progress: int = 0
    consecutive_failures: int = 0
    started_at: float = 0.0
    checkpoint_irreconcilable: bool = False

    def is_terminal(self) -> bool:
        return self.state in (
            SessionState.COMPLETED,
            SessionState.STOPPED,
            SessionState.FAILED,
        )


def make_session_id(frontier_ref: str) -> str:
    """Stable, frontier-derived id so a restart rehydrates the SAME session."""
    digest = hashlib.sha256(frontier_ref.encode("utf-8")).hexdigest()[:12]
    return f"unattended-{digest}"


@dataclass(frozen=True)
class WatchdogThresholds:
    """Fail-closed thresholds for the deterministic watchdog.

    These are *read* thresholds over existing consumption; they do not grant,
    raise, or widen any budget. They only decide between pause and stop.
    """

    retry_limit: int = 3
    repair_limit: int = 3
    budget_near: float = 0.9     # fraction of a research/network budget considered "near"
    perimeter_denial_limit: int = 0  # any denial is treated as a fault (fail-closed)


_HEALTH_EVENT_KINDS = (
    "session_start",
    "session_checkpoint",
    "health_decision",
    "session_paused",
    "session_stopped",
    "session_completed",
    "session_resumed",
)


@dataclass
class SessionJournalRecord:
    kind: str
    session_id: str
    ts: float
    data: dict = field(default_factory=dict)
