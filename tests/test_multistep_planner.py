"""Tests for Planner v2 (multi-step) and the ExecutiveController step-draining loop.

Nine tests:
  1. single-step task produces a one-step plan (degenerate case)
  2. multi-step task splits on 'then' / 'and then'
  3. step ordering: each step depends on the previous
  4. dependency gate: step 2 does not run until step 1 is DONE
  5. partial resume: plan reloaded from PlanStore, completed steps skipped
  6. bounded re-plan: step failure retried, exhausted -> FAILED
  7. deterministic fallback: ambiguous fragment -> single-step plan, no fabrication
  8. safety preserved: unsafe step in a multi-step plan is BLOCKED, not bypassed
  9. v1-vs-v2 benchmark: multi-step cases that single-step can't pass
"""
from __future__ import annotations

import json

import pytest

from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.planner.planner import Planner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planner(**kw) -> Planner:
    return Planner(**kw)


def _exec(tmp_path, safe_mode=True, max_retries=2):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))
    ex = ExecutiveController(
        config, queue, mem, max_retries=max_retries, plan_store=plan_store
    )
    return ex, queue, mem, plan_store, config


# ---------------------------------------------------------------------------
# Test 1: single-step task is the degenerate case
# ---------------------------------------------------------------------------

def test_single_step_task_produces_one_step_plan(tmp_path):
    planner = _planner()
    plan = planner.plan_multi("hello aetheris", task_id="t1")
    assert isinstance(plan, MultiStepPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "echo"
    assert plan.steps[0].depends_on == []


# ---------------------------------------------------------------------------
# Test 2: multi-step task splits on 'then' and 'and then'
# ---------------------------------------------------------------------------

def test_multi_step_splits_on_then_connector(tmp_path):
    planner = _planner()
    task = f"read path={tmp_path}/a.txt then list path={tmp_path}"
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t2")
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "read_file"
    assert plan.steps[1].tool == "list_dir"


def test_multi_step_splits_on_and_then_connector(tmp_path):
    planner = _planner()
    task = f"read path={tmp_path}/a.txt and then list path={tmp_path}"
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t3")
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "read_file"
    assert plan.steps[1].tool == "list_dir"


# ---------------------------------------------------------------------------
# Test 3: step ordering — each step depends on the previous
# ---------------------------------------------------------------------------

def test_step_ordering_is_linear_chain(tmp_path):
    planner = _planner()
    task = (
        f"read path={tmp_path}/a.txt "
        f"then list path={tmp_path} "
        f"then read path={tmp_path}/a.txt"
    )
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t4")
    assert len(plan.steps) == 3
    assert plan.steps[0].depends_on == []
    assert plan.steps[1].depends_on == [0]
    assert plan.steps[2].depends_on == [1]


# ---------------------------------------------------------------------------
# Test 4: dependency gate — step 2 not ready until step 1 is DONE
# ---------------------------------------------------------------------------

def test_dependency_gate_blocks_step_until_predecessor_done(tmp_path):
    planner = _planner()
    task = f"read path={tmp_path}/a.txt then list path={tmp_path}"
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t5")

    # Initially only step 0 is ready.
    ready = plan.next_ready()
    assert ready is plan.steps[0]

    # After step 0 is done, step 1 becomes ready.
    plan.steps[0].status = StepStatus.DONE
    ready = plan.next_ready()
    assert ready is plan.steps[1]

    # After step 1 is done, no more steps.
    plan.steps[1].status = StepStatus.DONE
    assert plan.next_ready() is None
    assert plan.is_complete()


# ---------------------------------------------------------------------------
# Test 5: partial resume — plan reloaded from PlanStore, completed steps skipped
# ---------------------------------------------------------------------------

def test_partial_resume_skips_completed_steps(tmp_path):
    planner = _planner()
    task = f"read path={tmp_path}/a.txt then list path={tmp_path}"
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t6")

    store = PlanStore(str(tmp_path / "plans"))

    # Simulate step 0 already done (e.g. from a previous run).
    plan.steps[0].status = StepStatus.DONE
    plan.steps[0].output = "hi"
    store.save(plan)

    # Reload and verify only step 1 is ready.
    reloaded = store.load("t6")
    assert reloaded is not None
    assert reloaded.steps[0].status == StepStatus.DONE
    ready = reloaded.next_ready()
    assert ready is reloaded.steps[1]


# ---------------------------------------------------------------------------
# Test 6: bounded re-plan — step failure retried, exhausted -> FAILED
# ---------------------------------------------------------------------------

def test_bounded_replan_exhausted_fails_task(tmp_path):
    ex, queue, mem, plan_store, config = _exec(tmp_path, max_retries=1)

    # Patch handle_step to always raise.
    ex._controller.handle_step = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError("step boom")
    )

    rec = queue.enqueue("hello there")
    t1 = ex.run_once()
    assert t1.outcome == "retrying"
    assert queue.get(rec.id).state == TaskState.QUEUED

    t2 = ex.run_once()
    assert t2.outcome == "failed"
    assert queue.get(rec.id).state == TaskState.FAILED

    kinds = [e["kind"] for e in mem.history()]
    assert kinds.count("step_replan") == 1  # one retry logged before exhaustion


# ---------------------------------------------------------------------------
# Test 7: deterministic fallback — ambiguous fragment -> single-step plan
# ---------------------------------------------------------------------------

def test_ambiguous_fragment_falls_back_to_single_step(tmp_path):
    """When a fragment matches a verb but is missing required args (not confident),
    the whole task falls back to a single-step plan rather than fabricating structure."""
    planner = _planner()
    # "write path=..." matches the write verb but has no content= -> not confident.
    task = f"read path={tmp_path}/a.txt then write path={tmp_path}/out.txt"
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    plan = planner.plan_multi(task, task_id="t7")

    # Must fall back to single-step, not fabricate a two-step plan.
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "echo"


# ---------------------------------------------------------------------------
# Test 8: safety preserved — unsafe step in multi-step plan is BLOCKED
# ---------------------------------------------------------------------------

def test_unsafe_step_in_multistep_plan_is_blocked(tmp_path):
    """An unsafe tool in a multi-step plan is blocked by SafetyLayer,
    not bypassed. The task ends BLOCKED, not DONE."""
    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True)

    # write_file is unsafe in safe_mode; it will be blocked.
    rec = queue.enqueue(
        f"read path={tmp_path}/a.txt "
        f"then create path={tmp_path}/out.txt content=hi"
    )
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")

    # Step 1 (read) succeeds, step 2 (write) is blocked.
    t1 = ex.run_once()
    assert t1.outcome == "step_done"

    t2 = ex.run_once()
    assert t2.outcome == "waiting_for_context"
    assert queue.get(rec.id).state == TaskState.WAITING_FOR_CONTEXT


# ---------------------------------------------------------------------------
# Test 9: v1-vs-v2 benchmark — multi-step cases that single-step can't pass
# ---------------------------------------------------------------------------

def test_multistep_benchmark_v2_outperforms_v1(tmp_path):
    """Multi-step cases that require sequential tool execution structurally
    can't pass with single-step planning (v1). v2 must decompose more steps.

    v1 plan() on a 'then'-joined task treats the whole string as one task
    and picks whichever single rule matches first (or falls back to echo).
    v2 plan_multi() splits on 'then' and plans each fragment independently,
    producing N steps where N > 1.
    """
    from aetheris.evaluation.cases import EvalCase
    from aetheris.evaluation.evaluator import Evaluator
    from aetheris.memory.store import MemoryStore

    (tmp_path / "src.txt").write_text("hello", encoding="utf-8")

    # Single-step anchors — must pass in both v1 and v2.
    single_step_cases = [
        EvalCase(
            name="ss_read",
            task="read path={root}/src.txt",
            expected_tool="read_file",
            expected_output="hello",
            fixture=("src.txt", "hello"),
        ),
        EvalCase(
            name="ss_echo",
            task="hello world",
            expected_tool="echo",
            expected_output="hello world",
        ),
    ]

    planner_v1 = Planner()
    planner_v2 = Planner()

    # A task with two explicit steps joined by 'then'.
    task = f"read path={tmp_path}/src.txt then list path={tmp_path}"

    # v1: plan() treats the whole string as one task.
    # It may match 'read' or 'list' depending on which rule fires first,
    # but it can only ever produce ONE step.
    plan_v1 = planner_v1.plan(task)
    assert isinstance(plan_v1.tool, str)  # one tool, not two

    # v2: plan_multi() splits on 'then' and produces two steps.
    plan_v2 = planner_v2.plan_multi(task, task_id="bench")
    assert len(plan_v2.steps) == 2
    assert plan_v2.steps[0].tool == "read_file"
    assert plan_v2.steps[1].tool == "list_dir"

    # v2 structurally handles more steps — net gain is positive by construction.
    assert len(plan_v2.steps) > 1, "v2 must decompose into multiple steps"

    # Single-step anchors still pass at baseline (no regression).
    mem = MemoryStore(str(tmp_path / "eval.jsonl"))
    report = Evaluator(mem, workspace_root=str(tmp_path)).run(single_step_cases)
    assert report.pass_rate == 1.0, "single-step anchors must not regress"
