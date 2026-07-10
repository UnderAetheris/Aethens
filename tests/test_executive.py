from aetheris.config import Config
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore


def _exec(tmp_path, improve_fn=None, safe_mode=True):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
    )
    return ExecutiveController(config, queue, mem, improve_fn=improve_fn), queue, mem


def test_run_once_drains_a_chat_task_to_done(tmp_path):
    ex, q, _ = _exec(tmp_path)
    rec = q.enqueue("hello there")
    tick = ex.run_once()
    assert tick.did_work and tick.outcome == "done"
    assert q.get(rec.id).state == TaskState.DONE


def test_blocked_task_when_safety_denies(tmp_path):
    ex, q, _ = _exec(tmp_path, safe_mode=True)
    rec = q.enqueue(f"create path={tmp_path}/out.txt content=hi")
    ex.run_once()
    assert q.get(rec.id).state == TaskState.BLOCKED


def test_idle_triggers_improvement_after_threshold(tmp_path):
    """Improvement fires only after idle_ticks_before_improve consecutive idle ticks."""
    calls = {"n": 0}

    def improver():
        calls["n"] += 1
        return True

    ex, q, mem = _exec(tmp_path, improve_fn=improver)
    # Ticks 1 and 2: idle but below threshold (default=3)
    tick1 = ex.run_once()
    assert not tick1.did_work and tick1.improved is None
    assert calls["n"] == 0
    tick2 = ex.run_once()
    assert calls["n"] == 0
    # Tick 3: threshold reached, improvement fires
    tick3 = ex.run_once()
    assert not tick3.did_work and tick3.improved is True
    assert calls["n"] == 1
    assert "executive_improve_done" in [e["kind"] for e in mem.history()]


def test_trigger_improvement_fires_immediately(tmp_path):
    """trigger_improvement() bypasses the idle threshold."""
    calls = {"n": 0}

    def improver():
        calls["n"] += 1
        return True

    ex, q, mem = _exec(tmp_path, improve_fn=improver)
    tick = ex.trigger_improvement()
    assert tick.improved is True
    assert calls["n"] == 1


def test_idle_counter_resets_when_work_arrives(tmp_path):
    """Queuing a task after idle ticks resets the counter so improvement doesn't fire early."""
    calls = {"n": 0}

    def improver():
        calls["n"] += 1
        return True

    ex, q, mem = _exec(tmp_path, improve_fn=improver)
    ex.run_once()  # idle tick 1
    ex.run_once()  # idle tick 2
    q.enqueue("hello")  # work arrives
    ex.run_once()  # drains task, resets idle counter
    assert calls["n"] == 0  # improvement must NOT have fired yet


def test_failed_task_is_retried_then_exhausted(tmp_path):
    """A step that always raises is retried max_retries times then the task is FAILED."""
    from aetheris.controller.controller import Controller
    from aetheris.planner.plan import MultiStepPlan, PlanStep

    class BoomPlanner:
        def plan(self, task):
            from aetheris.planner.planner import Plan
            return Plan("echo", task, "boom test")

        def plan_multi(self, task, task_id):
            return MultiStepPlan(
                task_id=task_id,
                steps=[PlanStep(tool="echo", arg=task, reason="boom test")],
            )

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(log_path=str(tmp_path / "ctrl.jsonl"), workspace_root=str(tmp_path))
    ctrl = Controller(config, memory=mem)
    ctrl.planner = BoomPlanner()
    # Patch handle_step to always raise
    ctrl.handle_step = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    ex = ExecutiveController(config, queue, mem, controller=ctrl, max_retries=2)

    rec = queue.enqueue("boom task")
    # Attempt 1 -> retrying
    t1 = ex.run_once()
    assert t1.outcome == "retrying"
    assert queue.get(rec.id).state == TaskState.QUEUED
    # Attempt 2 -> retrying
    t2 = ex.run_once()
    assert t2.outcome == "retrying"
    # Attempt 3 -> exhausted, final FAILED
    t3 = ex.run_once()
    assert t3.outcome == "failed"
    assert queue.get(rec.id).state == TaskState.FAILED
    kinds = [e["kind"] for e in mem.history()]
    assert kinds.count("step_replan") == 2


def test_improvement_does_not_run_while_work_pending(tmp_path):
    calls = {"n": 0}

    def improver():
        calls["n"] += 1
        return True

    ex, q, _ = _exec(tmp_path, improve_fn=improver)
    q.enqueue("hello")
    ex.run_once()
    assert calls["n"] == 0


def test_drain_processes_all_pending(tmp_path):
    ex, q, _ = _exec(tmp_path)
    ids = [q.enqueue(f"hello {i}").id for i in range(3)]
    ticks = ex.drain()
    assert all(q.get(i).state == TaskState.DONE for i in ids)
    assert len([t for t in ticks if t.outcome == "done"]) == 3


def test_state_survives_restart_mid_flight(tmp_path):
    ex, q, mem = _exec(tmp_path)
    rec = q.enqueue("hello")
    ex.run_once()
    q2 = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    assert q2.get(rec.id).state == TaskState.DONE
