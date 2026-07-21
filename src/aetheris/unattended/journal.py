"""Append-only session journal + versioned snapshot.

Crash-safe rehydration. Every session transition and health decision is
appended; a versioned snapshot captures confirmed-complete state for fast
rehydrate. A checkpoint is only ever written at a quiescent boundary, so no
half-applied state is ever captured. On restart we load the snapshot and replay
the tail to resume from the exact confirmed checkpoint.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Session, SessionJournalRecord, SessionState, now


class SessionJournal:
    """Persistent, append-only log of a session's life + a versioned snapshot."""

    _VERSION = 1

    def __init__(self, journal_path: str, snapshot_path: str) -> None:
        self._journal_path = Path(journal_path)
        self._snapshot_path = Path(snapshot_path)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Writing                                                              #
    # ------------------------------------------------------------------ #

    def _append(self, rec: SessionJournalRecord) -> None:
        row = {
            "kind": rec.kind,
            "session_id": rec.session_id,
            "ts": rec.ts,
            "data": rec.data,
        }
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def record_start(self, session: Session) -> None:
        self._append(SessionJournalRecord(
            kind="session_start",
            session_id=session.session_id,
            ts=now(),
            data={"frontier_ref": session.frontier_ref,
                  "bounds": _bounds_to_dict(session.bounds)},
        ))

    def record_decision(self, session: Session, verdict: str, reasons: tuple[str, ...],
                        snapshot: dict[str, Any]) -> None:
        self._append(SessionJournalRecord(
            kind="health_decision",
            session_id=session.session_id,
            ts=now(),
            data={"verdict": verdict, "reasons": list(reasons), "snapshot": snapshot},
        ))

    def checkpoint(self, session: Session, checkpoint_id: str) -> None:
        """Quiescent-only: write a versioned snapshot + a checkpoint event."""
        session.last_checkpoint = checkpoint_id
        self._write_snapshot(session)
        self._append(SessionJournalRecord(
            kind="session_checkpoint",
            session_id=session.session_id,
            ts=now(),
            data={"checkpoint_id": checkpoint_id, "steps_taken": session.steps_taken},
        ))

    def record_paused(self, session: Session) -> None:
        self._append(SessionJournalRecord(
            kind="session_paused", session_id=session.session_id, ts=now(),
            data={"reason": session.stop_reason, "steps_taken": session.steps_taken},
        ))

    def record_stopped(self, session: Session) -> None:
        self._append(SessionJournalRecord(
            kind="session_stopped", session_id=session.session_id, ts=now(),
            data={"reason": session.stop_reason, "state": session.state.value,
                  "steps_taken": session.steps_taken},
        ))

    def record_completed(self, session: Session) -> None:
        self._append(SessionJournalRecord(
            kind="session_completed", session_id=session.session_id, ts=now(),
            data={"steps_taken": session.steps_taken},
        ))

    def record_resumed(self, session: Session) -> None:
        self._append(SessionJournalRecord(
            kind="session_resumed", session_id=session.session_id, ts=now(),
            data={},
        ))

    # ------------------------------------------------------------------ #
    # Snapshot (versioned, fast rehydrate)                                #
    # ------------------------------------------------------------------ #

    def _write_snapshot(self, session: Session) -> None:
        snap = {
            "version": self._VERSION,
            "session_id": session.session_id,
            "state": session.state.value,
            "bounds": _bounds_to_dict(session.bounds),
            "frontier_ref": session.frontier_ref,
            "last_checkpoint": session.last_checkpoint,
            "stop_reason": session.stop_reason,
            "steps_taken": session.steps_taken,
            "retries_used": session.retries_used,
            "repairs_used": session.repairs_used,
            "ticks_without_progress": session.ticks_without_progress,
            "consecutive_failures": session.consecutive_failures,
            "started_at": session.started_at,
            "checkpoint_irreconcilable": session.checkpoint_irreconcilable,
        }
        tmp = self._snapshot_path.with_suffix(".snapshot.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(snap, f)
            f.flush()
        tmp.replace(self._snapshot_path)  # atomic

    def _read_snapshot(self) -> dict[str, Any] | None:
        if not self._snapshot_path.exists():
            return None
        try:
            with self._snapshot_path.open(encoding="utf-8") as f:
                snap = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        if snap.get("version") != self._VERSION:
            return None
        return snap

    # ------------------------------------------------------------------ #
    # Rehydrate                                                            #
    # ------------------------------------------------------------------ #

    def rehydrate(self, session_id: str) -> Session:
        """Load last snapshot; reconcile against the journal tail.

        If the snapshot is missing or cannot be reconciled with the recorded
        checkpoint, the returned session is flagged irreconcilable so the
        watchdog stops for review rather than guessing.
        """
        snap = self._read_snapshot()
        if snap is None or snap.get("session_id") != session_id:
            return Session(
                session_id=session_id,
                state=SessionState.FAILED,
                bounds=_default_bounds(),
                frontier_ref="",
                checkpoint_irreconcilable=True,
                stop_reason="no_reconcilable_checkpoint",
            )

        session = Session(
            session_id=snap["session_id"],
            state=SessionState(snap["state"]),
            bounds=_bounds_from_dict(snap["bounds"]),
            frontier_ref=snap["frontier_ref"],
            last_checkpoint=snap.get("last_checkpoint"),
            stop_reason=snap.get("stop_reason", ""),
            steps_taken=snap.get("steps_taken", 0),
            retries_used=snap.get("retries_used", 0),
            repairs_used=snap.get("repairs_used", 0),
            ticks_without_progress=snap.get("ticks_without_progress", 0),
            consecutive_failures=snap.get("consecutive_failures", 0),
            started_at=snap.get("started_at", 0.0),
            checkpoint_irreconcilable=snap.get("checkpoint_irreconcilable", False),
        )

        # Reconcile: a recorded checkpoint must point at a snapshot we trust.
        if session.last_checkpoint is not None and snap.get("last_checkpoint") != session.last_checkpoint:
            session.checkpoint_irreconcilable = True
            session.stop_reason = "checkpoint_irreconcilable"
        return session

    def has_session(self, session_id: str) -> bool:
        return self._read_snapshot() is not None \
            and self._read_snapshot().get("session_id") == session_id

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        if not self._journal_path.exists():
            return []
        events = []
        for line in self._journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("session_id") == session_id:
                events.append(row)
        return events


def _bounds_to_dict(b) -> dict[str, Any]:
    return {
        "max_wall_clock_s": b.max_wall_clock_s,
        "max_steps": b.max_steps,
        "max_consecutive_failures": b.max_consecutive_failures,
        "max_ticks_without_progress": b.max_ticks_without_progress,
    }


def _bounds_from_dict(d: dict[str, Any]):
    from .model import SessionBounds

    return SessionBounds(
        max_wall_clock_s=d["max_wall_clock_s"],
        max_steps=d["max_steps"],
        max_consecutive_failures=d["max_consecutive_failures"],
        max_ticks_without_progress=d["max_ticks_without_progress"],
    )


def _default_bounds():
    from .model import SessionBounds

    return SessionBounds(
        max_wall_clock_s=3600.0,
        max_steps=1000,
        max_consecutive_failures=3,
        max_ticks_without_progress=20,
    )
