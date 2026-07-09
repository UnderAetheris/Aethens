from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from .jsonl import JsonlStore


@dataclass(frozen=True)
class LearnedStep:
    """One accepted learning step: teach an intent one keyword."""

    intent: str
    keyword: str
    from_case: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LearnedStep":
        return cls(**d)


class LearnedKeywordStore:
    """Append-only journal of accepted planner keyword changes."""

    def __init__(self, path: str) -> None:
        self._store = JsonlStore(path)

    def append(self, intent: str, keyword: str, from_case: str) -> LearnedStep:
        step = LearnedStep(intent=intent, keyword=keyword, from_case=from_case, created_at=time.time())
        self._store.append(step.to_dict())
        return step

    def steps(self) -> list[LearnedStep]:
        return [LearnedStep.from_dict(d) for d in self._store.all()]

    def as_keywords(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for step in self.steps():
            bucket = result.setdefault(step.intent, [])
            if step.keyword not in bucket:
                bucket.append(step.keyword)
        return result

    def revert_last(self) -> LearnedStep | None:
        steps = self.steps()
        if not steps:
            return None
        removed = steps[-1]
        self._store.rewrite([s.to_dict() for s in steps[:-1]])
        return removed
