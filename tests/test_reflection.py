"""Tests for Reflection v1 — deterministic reflection engine.

12 tests:
  1.  success -> CONTINUE verdict
  2.  safety block -> REQUEST_CONTEXT (never RETRY)
  3.  transient failure within budget -> RETRY_STEP
  4.  transient failure, retries exhausted -> ABORT
  5.  repair suggestions valid -> INSERT_REPAIR_STEPS
  6.  repair suggestions with unknown tool -> ABORT (validation rejects)
  7.  repair count exceeds max -> ABORT (validation rejects)
  8.  reflection_decision is journaled for every step outcome
  9.  safety block routes task to WAITING_FOR_CONTEXT state (executive integration)
 10.  repair steps are inserted into live plan and task re-queued (executive integration)
 11.  restart-mid-repair: plan with inserted repair steps survives reload from PlanStore
 12.  safety-neutrality: blocked count must not increase after reflection is active
"""
from __future__ import annotations


from aetheris.config import Config
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.reflection.engine import ReflectionEngine, StepOutcome, Verdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(task_id: str, tools: list[str]) -> MultiStepPlan:
    steps = [PlanStep(tool=t, arg="x", reason="test") for t in tools]
    for i in range(1, len(steps)):
        steps[i].depends_on = [i - 1]
    return MultiStepPlan(task_id=task_id, steps=steps)


def _outcome(ok: bool, blocked: bool = False, attempt: int = 1,
             repairs: list[tuple[str, str]] | None = None) -> StepOutcome:
    return StepOutcome(
        task_id="t1", step_index=0, tool="echo", arg="x",
        ok=ok, output="blocked: denied" if blocked else ("ok" if ok else "err"),
        blocked=blocked, attempt=attempt,
        repair_suggestions=repairs or [],
    )


def _exec(tmp_path, safe_mode=True, max_retries=2, reflection=None):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))
    ex = ExecutiveController(
        config, queue, mem,
        max_retries=max_retries,
        plan_store=plan_store,
        reflection=reflection,
    )
    return ex, queue, mem, plan_store, config


# ---------------------------------------------------------------------------
# 1. success -> CONTINUE
# ---------------------------------------------------------------------------

def test_success_verdict_is_continue():
    engine = ReflectionEngine(registry_tools=("echo",))
    plan = _plan("t1", ["echo"])
    result = engine.reflect(_outcome(ok=True), plan)
    assert result.verdict == Verdict.CONTINUE


# ---------------------------------------------------------------------------
# 2. safety block -> REQUEST_CONTEXT, never RETRY
# ---------------------------------------------------------------------------

def test_safety_block_verdict_is_request_context():
    engine = ReflectionEngine(registry_tools=("echo",))
    plan = _plan("t1", ["echo"])
    result = engine.reflect(_outcome(ok=False, blocked=True), plan)
    assert result.verdict == Verdict.REQUEST_CONTEXT
    assert result.verdict != Verdict.RETRY_STEP


# ---------------------------------------------------------------------------
# 3. transient failure within budget -> RETRY_STEP
# ---------------------------------------------------------------------------

def test_transient_failure_within_budget_is_retry():
    engine = ReflectionEngine(registry_tools=("echo",))
    plan = _plan("t1", ["echo"])
    result = engine.reflect(_outcome(ok=False, attempt=1), plan)
    assert result.verdict == Verdict.RETRY_STEP


# ---------------------------------------------------------------------------
# 4. transient failure, retries exhausted -> ABORT
# ---------------------------------------------------------------------------

def test_transient_failure_exhausted_is_abort():
    from aetheris.reflection.engine import _MAX_REFLECT_RETRIES
    engine = ReflectionEngine(registry_tools=("echo",))
    plan = _plan("t1", ["echo"])
    result = engine.reflect(_outcome(ok=False, attempt=_MAX_REFLECT_RETRIES), plan)
    assert result.verdict == Verdict.ABORT


# ---------------------------------------------------------------------------
# 5. valid repair suggestions -> INSERT_REPAIR_STEPS
# ---------------------------------------------------------------------------

def test_valid_repair_suggestions_insert_verdict():
    engine = ReflectionEngine(registry_tools=("echo", "read_file"))
    plan = _plan("t1", ["echo"])
    repairs = [("read_file", "path=x"), ("echo", "done")]
    result = engine.reflect(_outcome(ok=False, repairs=repairs), plan)
    assert result.verdict == Verdict.INSERT_REPAIR_STEPS
    assert result.repair_steps == repairs


# ---------------------------------------------------------------------------
# 6. repair with unknown tool -> ABORT
# ---------------------------------------------------------------------------

def test_repair_with_unknown_tool_is_abort():
    engine = ReflectionEngine(registry_tools=("echo",))
    plan = _plan("t1", ["echo"])
    repairs = [("nonexistent_tool", "arg")]
    result = engine.reflect(_outcome(ok=False, repairs=repairs), plan)
    assert result.verdict == Verdict.ABORT


# ---------------------------------------------------------------------------
# 7. repair count exceeds max -> ABORT
# ---------------------------------------------------------------------------

def test_repair_exceeds_max_count_is_abort():
    engine = ReflectionEngine(registry_tools=("echo",), max_repair_steps=2)
    plan = _plan("t1", ["echo"])
    repairs = [("echo", "a"), ("echo", "b"), ("echo", "c")]  # 3 > max 2
    result = engine.reflect(_outcome(ok=False, repairs=repairs), plan)
    assert result.verdict == Verdict.ABORT


# ---------------------------------------------------------------------------
# 8. reflection_decision is journaled for every step outcome
# ---------------------------------------------------------------------------

def test_reflection_decision_is_journaled(tmp_path):
    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=False)
    queue.enqueue("hello there")
    ex.run_once()
    kinds = [e["kind"] for e in mem.history()]
    assert "reflection_decision" in kinds


# ---------------------------------------------------------------------------
# 9. safety block routes task to WAITING_FOR_CONTEXT (executive integration)
# ---------------------------------------------------------------------------

def test_safety_block_routes_to_waiting_for_context(tmp_path):
    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True)
    # write_file is blocked in safe_mode
    rec = queue.enqueue(f"create path={tmp_path}/out.txt content=hi")
    ex.run_once()
    assert queue.get(rec.id).state == TaskState.WAITING_FOR_CONTEXT
    kinds = [e["kind"] for e in mem.history()]
    assert "reflection_decision" in kinds
    decisions = [e for e in mem.history() if e["kind"] == "reflection_decision"]
    assert decisions[-1]["data"]["verdict"] == Verdict.REQUEST_CONTEXT.value


# ---------------------------------------------------------------------------
# 10. repair steps inserted into live plan, task re-queued
# ---------------------------------------------------------------------------

def test_repair_steps_inserted_and_task_requeued(tmp_path):
    """When reflection returns INSERT_REPAIR_STEPS, the plan grows and the
    task is re-queued so the executive picks up the repair steps next tick."""
    from aetheris.reflection.engine import ReflectionEngine, Verdict

    call_count = {"n": 0}

    class RepairReflection(ReflectionEngine):
        def reflect(self, outcome, plan):
            from aetheris.reflection.engine import ReflectionResult
            call_count["n"] += 1
            if not outcome.ok and not outcome.blocked and call_count["n"] == 1:
                return ReflectionResult(
                    verdict=Verdict.INSERT_REPAIR_STEPS,
                    reason="test repair",
                    repair_steps=[("echo", "repaired")],
                )
            return super().reflect(outcome, plan)

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=False,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))
    ex = ExecutiveController(
        config, queue, mem,
        max_retries=2,
        plan_store=plan_store,
        reflection=RepairReflection(registry_tools=("echo",)),
    )
    # Patch handle_step to fail once then succeed
    fail_once = {"done": False}
    original = ex._controller.handle_step

    def patched(tool, arg, **kw):
        if not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("transient")
        return original(tool, arg, **kw)

    ex._controller.handle_step = patched

    rec = queue.enqueue("hello")
    t1 = ex.run_once()
    assert t1.outcome == "repair_inserted"
    assert queue.get(rec.id).state == TaskState.QUEUED

    kinds = [e["kind"] for e in mem.history()]
    assert "repair_inserted" in kinds


# ---------------------------------------------------------------------------
# 11. restart-mid-repair: plan with repair steps survives PlanStore reload
# ---------------------------------------------------------------------------

def test_repair_plan_survives_restart(tmp_path):
    from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore

    plan = MultiStepPlan(task_id="t_restart", steps=[
        PlanStep(tool="echo", arg="step1", reason="original"),
    ])
    plan.steps[0].status = StepStatus.FAILED

    inserted = plan.insert_repair_after(0, [("echo", "repair1")])
    assert inserted
    assert len(plan.steps) == 2
    assert plan.steps[1].tool == "echo"
    assert plan.steps[1].arg == "repair1"

    store = PlanStore(str(tmp_path / "plans"))
    store.save(plan)

    reloaded = store.load("t_restart")
    assert reloaded is not None
    assert len(reloaded.steps) == 2
    assert reloaded.steps[1].arg == "repair1"
    assert reloaded.steps[0].status == StepStatus.FAILED


# ---------------------------------------------------------------------------
# 12. safety-neutrality: reflection must not increase blocked/unsafe attempts
# ---------------------------------------------------------------------------

def test_safety_neutrality_blocked_count_does_not_increase(tmp_path):
    """Reflection must not cause more safety blocks than would occur without it.

    Baseline: run an unsafe task without reflection active (reflection is
    always active now, but we verify the block count is exactly 1 — the
    SafetyLayer fires once and reflection routes to WAITING_FOR_CONTEXT,
    not a retry loop that would fire the safety gate multiple times).
    """
    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True)
    rec = queue.enqueue(f"create path={tmp_path}/out.txt content=hi")
    ex.run_once()

    # The task must be in a terminal-ish state (WAITING_FOR_CONTEXT), not retrying.
    assert queue.get(rec.id).state == TaskState.WAITING_FOR_CONTEXT

    # reflection_decision must appear exactly once with REQUEST_CONTEXT —
    # reflection never retried the block (which would produce multiple decisions).
    decisions = [e for e in mem.history() if e["kind"] == "reflection_decision"]
    assert len(decisions) == 1
    assert decisions[0]["data"]["verdict"] == Verdict.REQUEST_CONTEXT.value
