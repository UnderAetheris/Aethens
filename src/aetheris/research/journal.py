"""Append-only research journal.

Same discipline as the experience stores and the hierarchical ``goal_graph``
journal: every egress decision, fetch, extraction, and final bundle is appended
as an immutable line. The journal is the only durable write the Research Engine
makes (besides a bounded content cache). It records *what was queried, fetched,
extracted, with hashes and citations* — never memory, never config, never
skills. A run is fully reconstructable from it.

Strictly append-only: it never edits or deletes a line. A denied request is
just another line, not a mutation of history.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ResearchJournal:
    def __init__(self, journal_dir: str) -> None:
        self._dir = Path(journal_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "research.journal.jsonl"

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        entry = {"kind": kind, "timestamp": time.time(), **payload}
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def lines(self, kind: str | None = None) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if kind is None or rec.get("kind") == kind:
                    out.append(rec)
        return out

    def egress_attempts(self) -> int:
        return len(self.lines("perimeter_denied")) + len(self.lines("perimeter_allowed"))
