from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def make_id(prefix: str, count: int, payload: str) -> str:
    """Deterministic id: prefix-0001-<short content hash>."""
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]
    return f"{prefix}-{count:04d}-{digest}"


class JsonlStore:
    """Generic append-only JSONL store over flat dict records.

    Shared engine for knowledge and experience memory. Deterministic,
    file-based, no external dependencies.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def append(self, record: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def all(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def count(self) -> int:
        return len(self.all())

    def search(
        self,
        query: str | None = None,
        fields: tuple[str, ...] = (),
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Deterministic filter.

        - `query`: case-insensitive substring match across `fields`.
        - `where`: exact-match filter on top-level keys. If the record value
          is a list (e.g. tags), membership is tested instead of equality.
        """
        results: list[dict[str, Any]] = []
        q = query.lower() if query else None
        for rec in self.all():
            if q is not None:
                hay = " ".join(str(rec.get(f, "")) for f in fields).lower()
                if q not in hay:
                    continue
            if where:
                ok = True
                for key, val in where.items():
                    cur = rec.get(key)
                    if isinstance(cur, list):
                        if val not in cur:
                            ok = False
                            break
                    elif cur != val:
                        ok = False
                        break
                if not ok:
                    continue
            results.append(rec)
        return results
