from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from .jsonl import JsonlStore, make_id


@dataclass(frozen=True)
class ExperienceEntry:
    """A lesson from a real failure: what broke, why, and how it was fixed."""

    id: str
    problem: str
    cause: str
    fix: str
    evidence: str = ""
    related_task: str | None = None
    related_eval_case: str | None = None
    confidence: float = 0.5
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExperienceEntry":
        return cls(**d)


class ExperienceStore:
    """Typed view over a JSONL store for ExperienceEntry records."""

    def __init__(self, path: str) -> None:
        self._store = JsonlStore(path)

    def add(
        self,
        problem: str,
        cause: str,
        fix: str,
        evidence: str = "",
        related_task: str | None = None,
        related_eval_case: str | None = None,
        confidence: float = 0.5,
    ) -> ExperienceEntry:
        entry = ExperienceEntry(
            id=make_id("exp", self._store.count() + 1, problem + fix),
            problem=problem,
            cause=cause,
            fix=fix,
            evidence=evidence,
            related_task=related_task,
            related_eval_case=related_eval_case,
            confidence=confidence,
            created_at=time.time(),
        )
        self._store.append(entry.to_dict())
        return entry

    def all(self) -> list[ExperienceEntry]:
        return [ExperienceEntry.from_dict(d) for d in self._store.all()]

    def get(self, entry_id: str) -> ExperienceEntry | None:
        for d in self._store.all():
            if d.get("id") == entry_id:
                return ExperienceEntry.from_dict(d)
        return None

    def search(self, query: str | None = None) -> list[ExperienceEntry]:
        rows = self._store.search(query=query, fields=("problem", "cause", "fix", "evidence"))
        return [ExperienceEntry.from_dict(d) for d in rows]

    def for_task(self, related_task: str) -> list[ExperienceEntry]:
        rows = self._store.search(where={"related_task": related_task})
        return [ExperienceEntry.from_dict(d) for d in rows]

    def for_eval_case(self, related_eval_case: str) -> list[ExperienceEntry]:
        rows = self._store.search(where={"related_eval_case": related_eval_case})
        return [ExperienceEntry.from_dict(d) for d in rows]
