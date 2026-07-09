from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from ..memory.jsonl import JsonlStore, make_id
from ..memory.store import MemoryStore


class TaskState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"


_ALLOWED: dict[TaskState, set[TaskState]] = {
    TaskState.QUEUED: {TaskState.PLANNING, TaskState.FAILED},
    TaskState.PLANNING: {TaskState.EXECUTING, TaskState.BLOCKED, TaskState.FAILED},
    TaskState.EXECUTING: {TaskState.DONE, TaskState.BLOCKED, TaskState.FAILED},
    TaskState.DONE: set(),
    TaskState.BLOCKED: {TaskState.QUEUED},
    TaskState.FAILED: {TaskState.QUEUED},
}


@dataclass
class TaskRecord:
    id: str
    task: str
    state: TaskState
    detail: str = ""
    priority: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskRecord":
        d = dict(d)
        d["state"] = TaskState(d["state"])
        return cls(**d)


class IllegalTransition(Exception):
    pass


class TaskQueue:
    """Persistent, auditable task queue backed by a journal."""

    def __init__(self, journal_path: str, memory: MemoryStore) -> None:
        self._store = JsonlStore(journal_path)
        self._memory = memory

    def enqueue(self, task: str, priority: int = 0) -> TaskRecord:
        now = time.time()
        record = TaskRecord(
            id=make_id("task", self._store.count() + 1, task),
            task=task,
            state=TaskState.QUEUED,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        self._store.append(record.to_dict())
        self._memory.record(
            "queue_transition",
            {"id": record.id, "to": record.state.value, "detail": "enqueued"},
        )
        return record

    def transition(self, task_id: str, new_state: TaskState, detail: str = "") -> TaskRecord:
        current = self.get(task_id)
        if current is None:
            raise KeyError(f"unknown task {task_id}")
        if new_state not in _ALLOWED[current.state]:
            raise IllegalTransition(f"{current.state.value} -> {new_state.value}")
        current.state = new_state
        current.detail = detail
        current.updated_at = time.time()
        self._store.append(current.to_dict())
        self._memory.record(
            "queue_transition",
            {"id": task_id, "to": new_state.value, "detail": detail},
        )
        return current

    def _current(self) -> dict[str, TaskRecord]:
        latest: dict[str, TaskRecord] = {}
        for row in self._store.all():
            rec = TaskRecord.from_dict(row)
            latest[rec.id] = rec
        return latest

    def get(self, task_id: str) -> TaskRecord | None:
        return self._current().get(task_id)

    def all(self) -> list[TaskRecord]:
        return list(self._current().values())

    def pending(self) -> list[TaskRecord]:
        q = [r for r in self._current().values() if r.state == TaskState.QUEUED]
        return sorted(q, key=lambda r: (-r.priority, r.created_at))

    def next_queued(self) -> TaskRecord | None:
        pend = self.pending()
        return pend[0] if pend else None

    def is_idle(self) -> bool:
        return not self.pending()
