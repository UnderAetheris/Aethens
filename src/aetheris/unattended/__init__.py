"""Unattended Run Loop & Health Watchdog (v0).

A bounded, fail-closed supervisor that composes, never bypasses or expands,
the existing Executive/orchestrator. It drives the existing gated spine one
step at a time, monitors deterministic health, checkpoints at safe points, and
resumes cleanly after interruption. It grants no new execution authority and
adds no execution path: it may stop work, it may never expand it.

Default-off. With unattended mode off, the executive runs exactly as today.
"""
from __future__ import annotations

from .journal import SessionJournal
from .model import (
    HealthDecision,
    HealthSnapshot,
    HealthVerdict,
    Session,
    SessionBounds,
    SessionState,
    WatchdogThresholds,
    make_session_id,
)
from .sampler import StaticSampler, build_sampler
from .supervisor import UnattendedSupervisor
from .watchdog import HealthWatchdog

__all__ = [
    "Session",
    "SessionState",
    "SessionBounds",
    "SessionJournal",
    "HealthSnapshot",
    "HealthDecision",
    "HealthVerdict",
    "WatchdogThresholds",
    "HealthWatchdog",
    "StaticSampler",
    "build_sampler",
    "UnattendedSupervisor",
    "make_session_id",
]
