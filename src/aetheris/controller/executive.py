from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from ..memory.store import MemoryStore
from .controller import Controller
from .queue import TaskQueue, TaskState


@dataclass
class Tick:
    did_work: bool
    task_id: str | None = None
    outcome: str | None = None
    improved: bool | None = None


class ExecutiveController:
    """Orchestrates live work and idle improvement without bypassing safety."""

    def __init__(
        self,
        config: Config,
        queue: TaskQueue,
        memory: MemoryStore,
        controller: Controller | None = None,
        improve_fn=None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._memory = memory
        self._controller = controller or Controller(config)
        self._improve_fn = improve_fn

    def run_once(self) -> Tick:
        nxt = self._queue.next_queued()
        if nxt is None:
            return self._maybe_improve()
        return self._run_task(nxt.id)

    def _run_task(self, task_id: str) -> Tick:
        rec = self._queue.transition(task_id, TaskState.PLANNING, "executive picked up")
        self._queue.transition(task_id, TaskState.EXECUTING, "handed to controller")
        try:
            result = self._controller.handle(rec.task)
        except Exception as exc:  # genuine execution error
            self._queue.transition(task_id, TaskState.FAILED, f"exception: {exc!r}")
            return Tick(did_work=True, task_id=task_id, outcome="failed")

        if not result.ok:
            self._queue.transition(task_id, TaskState.BLOCKED, result.output)
            return Tick(did_work=True, task_id=task_id, outcome="blocked")

        self._queue.transition(task_id, TaskState.DONE, result.output)
        return Tick(did_work=True, task_id=task_id, outcome="done")

    def _maybe_improve(self) -> Tick:
        if self._improve_fn is None:
            self._memory.record("executive_idle", {"detail": "no improver configured"})
            return Tick(did_work=False)
        self._memory.record("executive_improve_start", {})
        improved = bool(self._improve_fn())
        self._memory.record("executive_improve_done", {"improved": improved})
        return Tick(did_work=False, improved=improved)

    def drain(self, max_tasks: int = 100) -> list[Tick]:
        ticks: list[Tick] = []
        while self._queue.next_queued() is not None and len(ticks) < max_tasks:
            ticks.append(self.run_once())
        return ticks
