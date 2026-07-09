from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


class MemoryStore:
    """Append-only task/lesson log. JSONL now; swap for a real store later."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def record(self, kind: str, data: dict[str, Any]) -> None:
        entry = {"ts": time.time(), "kind": kind, "data": data}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def history(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
