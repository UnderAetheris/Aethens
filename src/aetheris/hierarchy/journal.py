"""Append-only `goal_graph` journal + versioned snapshot.

Same discipline as `repo_scan` and the experience stores: every state
transition of every subgoal is appended as an immutable line, alongside a
versioned snapshot of the whole graph. On restart, load the snapshot and
resume from the exact frontier; completed subtrees stay completed, in-flight
ones resume, and nothing re-runs that already succeeded. "What was done, in
what order, and why" is fully reconstructable.

The journal is strictly append-only: it never edits or deletes a line. A
cancellation is just another transition line, not a mutation of history.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .model import GoalGraph, SubGoalState


class GoalJournal:
    """Append-only transition log + snapshot store for one or many goals."""

    def __init__(self, journal_dir: str) -> None:
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._journal_path = self._dir / "goal_graph.journal.jsonl"
        self._snap_dir = self._dir / "snapshots"
        self._snap_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Append-only transition log                                          #
    # ------------------------------------------------------------------ #

    def record(self, goal_id: str, transition: dict[str, Any]) -> None:
        """Append one immutable transition line. Never edits prior lines."""
        entry = {
            "goal_id": goal_id,
            "timestamp": time.time(),
            **transition,
        }
        with open(self._journal_path, "a", encoding="utf-8") as f:
            f.write(__import__("json").dumps(entry, default=str) + "\n")

    def transitions(self, goal_id: str | None = None) -> list[dict[str, Any]]:
        if not self._journal_path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self._journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = __import__("json").loads(line)
                if goal_id is None or rec.get("goal_id") == goal_id:
                    out.append(rec)
        return out

    def reconstruct(self, goal_id: str) -> dict[str, str]:
        """Replay the journal to the final state of every subgoal.

        Returns {subgoal_id: final_state_value}. Pure read; identical every
        time for the same journal — the run is fully reconstructable.
        """
        final: dict[str, str] = {}
        for rec in self.transitions(goal_id):
            sid = rec.get("subgoal_id")
            to_state = rec.get("to_state")
            if sid is not None and to_state is not None:
                final[sid] = to_state
        return final

    # ------------------------------------------------------------------ #
    # Versioned snapshot                                                  #
    # ------------------------------------------------------------------ #

    def save(self, graph: GoalGraph) -> None:
        """Write a versioned snapshot of the current graph state."""
        path = self._snap_dir / f"{graph.goal_id}.v{graph.version}.json"
        path.write_text(
            __import__("json").dumps(graph.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

    def load(self, goal_id: str) -> GoalGraph | None:
        """Load the latest snapshot for a goal, or None if none exists."""
        snaps = sorted(self._snap_dir.glob(f"{goal_id}.v*.json"))
        if not snaps:
            return None
        latest = snaps[-1]
        data = __import__("json").loads(latest.read_text(encoding="utf-8"))
        return GoalGraph.from_dict(data)

    def resume(self, goal_id: str) -> GoalGraph | None:
        """Resume from the exact frontier: load snapshot, replay journal tail.

        The snapshot already carries the latest per-node state, so the frontier
        is exact. Returns None if there is nothing to resume.
        """
        graph = self.load(goal_id)
        if graph is None:
            return None
        # Defensive: re-apply journal tail in case a transition landed after the
        # last snapshot (frontier is never lost).
        final = self.reconstruct(goal_id)
        for sid, state in final.items():
            run = graph.nodes.get(sid)
            if run is not None:
                run.state = SubGoalState(state)
        return graph
