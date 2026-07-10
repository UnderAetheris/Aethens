from __future__ import annotations

from dataclasses import dataclass, field

from ..config import Config
from ..memory.store import MemoryStore
from .controller import Controller
from .queue import TaskQueue, TaskState

# How many consecutive idle ticks must pass before the improvement loop runs.
_IDLE_TICKS_BEFORE_IMPROVE = 3

# Maximum times a FAILED task is automatically re-queued before giving up.
_MAX_RETRIES = 2


@dataclass
class Tick:
    did_work: bool
    task_id: str | None = None
    outcome: str | None = None
    improved: bool | None = None


class ExecutiveController:
    """Orchestrates live work and idle-time improvement without bypassing safety.

    Policy:
    - While tasks are queued, drain them one at a time.
    - Transient failures (exception during execution) are retried up to
      _MAX_RETRIES times before the task is left in FAILED state.
    - When the queue is empty for _IDLE_TICKS_BEFORE_IMPROVE consecutive
      ticks, run one improvement attempt (eval + learn), then reset the
      idle counter so the loop doesn't thrash.
    """

    def __init__(
        self,
        config: Config,
        queue: TaskQueue,
        memory: MemoryStore,
        controller: Controller | None = None,
        improve_fn=None,
        idle_ticks_before_improve: int = _IDLE_TICKS_BEFORE_IMPROVE,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._config = config
        self._queue = queue
        self._memory = memory
        self._controller = controller or Controller(config)
        self._improve_fn = improve_fn
        self._idle_threshold = idle_ticks_before_improve
        self._max_retries = max_retries
        self._idle_ticks: int = 0
        self._retry_counts: dict[str, int] = {}

    def run_once(self) -> Tick:
        nxt = self._queue.next_queued()
        if nxt is None:
            return self._on_idle()
        self._idle_ticks = 0  # reset idle counter whenever real work exists
        return self._run_task(nxt.id)

    def _run_task(self, task_id: str) -> Tick:
        rec = self._queue.transition(task_id, TaskState.PLANNING, "executive picked up")
        self._queue.transition(task_id, TaskState.EXECUTING, "handed to controller")
        try:
            result = self._controller.handle(rec.task)
        except Exception as exc:  # transient execution error — may retry
            retries = self._retry_counts.get(task_id, 0)
            if retries < self._max_retries:
                self._retry_counts[task_id] = retries + 1
                self._queue.transition(
                    task_id, TaskState.FAILED, f"exception (attempt {retries + 1}): {exc!r}"
                )
                self._queue.transition(task_id, TaskState.QUEUED, "retrying")
                self._memory.record(
                    "executive_retry",
                    {"id": task_id, "attempt": retries + 1, "reason": repr(exc)},
                )
                return Tick(did_work=True, task_id=task_id, outcome="retrying")
            self._queue.transition(task_id, TaskState.FAILED, f"exception: {exc!r}")
            self._retry_counts.pop(task_id, None)
            return Tick(did_work=True, task_id=task_id, outcome="failed")

        self._retry_counts.pop(task_id, None)  # success clears retry counter
        if not result.ok:
            self._queue.transition(task_id, TaskState.BLOCKED, result.output)
            return Tick(did_work=True, task_id=task_id, outcome="blocked")

        self._queue.transition(task_id, TaskState.DONE, result.output)
        return Tick(did_work=True, task_id=task_id, outcome="done")

    def _on_idle(self) -> Tick:
        self._idle_ticks += 1
        if self._improve_fn is None or self._idle_ticks < self._idle_threshold:
            self._memory.record(
                "executive_idle",
                {
                    "idle_ticks": self._idle_ticks,
                    "threshold": self._idle_threshold,
                    "detail": "no improver configured" if self._improve_fn is None
                              else "waiting for idle threshold",
                },
            )
            return Tick(did_work=False)
        # Threshold reached — run one improvement cycle then reset.
        self._idle_ticks = 0
        self._memory.record("executive_improve_start", {})
        improved = bool(self._improve_fn())
        self._memory.record("executive_improve_done", {"improved": improved})
        return Tick(did_work=False, improved=improved)

    def drain(self, max_tasks: int = 100) -> list[Tick]:
        """Process all currently queued tasks (up to max_tasks). Does not trigger improvement."""
        ticks: list[Tick] = []
        while self._queue.next_queued() is not None and len(ticks) < max_tasks:
            ticks.append(self.run_once())
        return ticks

    def trigger_improvement(self) -> Tick:
        """Run one improvement cycle immediately, regardless of idle state.

        Used by the API and tests to force an improvement attempt on demand.
        Resets the idle counter so the scheduled cycle doesn't double-fire.
        """
        if self._improve_fn is None:
            self._memory.record("executive_improve_skipped", {"reason": "no improver configured"})
            return Tick(did_work=False, improved=False)
        self._idle_ticks = 0
        self._memory.record("executive_improve_start", {"triggered": "manual"})
        improved = bool(self._improve_fn())
        self._memory.record("executive_improve_done", {"improved": improved})
        return Tick(did_work=False, improved=improved)
