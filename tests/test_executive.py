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


def test_idle_triggers_improvement(tmp_path):
    calls = {"n": 0}

    def improver():
        calls["n"] += 1
        return True

    ex, q, mem = _exec(tmp_path, improve_fn=improver)
    tick = ex.run_once()
    assert not tick.did_work and tick.improved is True
    assert calls["n"] == 1
    assert "executive_improve_done" in [e["kind"] for e in mem.history()]


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
