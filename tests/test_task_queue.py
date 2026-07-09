import pytest

from aetheris.controller.queue import IllegalTransition, TaskQueue, TaskState
from aetheris.memory.store import MemoryStore


def _queue(tmp_path):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    return TaskQueue(str(tmp_path / "queue.jsonl"), mem), mem


def test_enqueue_creates_queued_task(tmp_path):
    q, _ = _queue(tmp_path)
    rec = q.enqueue("do a thing")
    assert rec.state == TaskState.QUEUED
    assert q.get(rec.id).task == "do a thing"


def test_legal_transitions_update_state(tmp_path):
    q, _ = _queue(tmp_path)
    rec = q.enqueue("t")
    q.transition(rec.id, TaskState.PLANNING)
    q.transition(rec.id, TaskState.EXECUTING)
    q.transition(rec.id, TaskState.DONE, "ok")
    assert q.get(rec.id).state == TaskState.DONE


def test_illegal_transition_rejected(tmp_path):
    q, _ = _queue(tmp_path)
    rec = q.enqueue("t")
    with pytest.raises(IllegalTransition):
        q.transition(rec.id, TaskState.DONE)


def test_transitions_logged_to_memory(tmp_path):
    q, mem = _queue(tmp_path)
    rec = q.enqueue("t")
    q.transition(rec.id, TaskState.PLANNING)
    kinds = [e["kind"] for e in mem.history()]
    assert kinds.count("queue_transition") == 2


def test_state_survives_restart(tmp_path):
    q, mem = _queue(tmp_path)
    rec = q.enqueue("t")
    q.transition(rec.id, TaskState.PLANNING)
    q2 = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    assert q2.get(rec.id).state == TaskState.PLANNING


def test_priority_and_fifo_ordering(tmp_path):
    q, _ = _queue(tmp_path)
    a = q.enqueue("low-1", priority=0)
    b = q.enqueue("high", priority=5)
    c = q.enqueue("low-2", priority=0)
    order = [r.id for r in q.pending()]
    assert order[0] == b.id
    assert order[1:] == [a.id, c.id]


def test_is_idle_reflects_pending(tmp_path):
    q, _ = _queue(tmp_path)
    assert q.is_idle()
    rec = q.enqueue("t")
    assert not q.is_idle()
    q.transition(rec.id, TaskState.PLANNING)
    assert q.is_idle()
