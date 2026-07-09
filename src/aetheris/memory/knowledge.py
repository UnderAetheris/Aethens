from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .jsonl import JsonlStore, make_id


@dataclass(frozen=True)
class KnowledgeEntry:
    """A durable fact, documentation summary, or reusable pattern."""

    id: str
    title: str
    source: str
    summary: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "KnowledgeEntry":
        return cls(**d)


class KnowledgeStore:
    """Typed view over a JSONL store for KnowledgeEntry records."""

    def __init__(self, path: str) -> None:
        self._store = JsonlStore(path)

    def add(
        self,
        title: str,
        source: str,
        summary: str,
        tags: list[str] | None = None,
        confidence: float = 0.5,
    ) -> KnowledgeEntry:
        tags = tags or []
        entry = KnowledgeEntry(
            id=make_id("know", self._store.count() + 1, title + summary),
            title=title,
            source=source,
            summary=summary,
            tags=tags,
            confidence=confidence,
            created_at=time.time(),
        )
        self._store.append(entry.to_dict())
        return entry

    def all(self) -> list[KnowledgeEntry]:
        return [KnowledgeEntry.from_dict(d) for d in self._store.all()]

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        for d in self._store.all():
            if d.get("id") == entry_id:
                return KnowledgeEntry.from_dict(d)
        return None

    def search(
        self, query: str | None = None, tag: str | None = None
    ) -> list[KnowledgeEntry]:
        where = {"tags": tag} if tag else None
        rows = self._store.search(
            query=query, fields=("title", "summary", "source"), where=where
        )
        return [KnowledgeEntry.from_dict(d) for d in rows]
