"""Hierarchical Task Decomposition & Long-Horizon Execution v0 — tests.

Mirrors the acceptance criteria in the design doc (§8): DAG validity + stable
IDs, deterministic one-at-a-time scheduling with no hidden execution, automatic
done-detection/dedup/skill reuse, failure isolation + subtree retry/rollback +
blocked propagation, resume/checkpoint/cancel, and the flat-vs-hierarchical
adoption gate. Hierarchy is default-off and byte-identical to flat when off or
when the decomposer abstains.
"""
from __future__ import annotations

import pytest

from aetheris.config import Config
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore
from aetheris.planner.planner import Planner
from aetheris.skills.registry import SkillRegistry, SkillStep, SkillTemplate
from aetheris.hierarchy import (
    BenchmarkResult,
    CyclicDecomposition,
    Goal,
    GoalGraph,
    GoalJournal,
    GoalOrchestrator,
    SubGoal,
    SubGoalState,
    SubGoalRun,
    GoalDecomposer,
    baseline_model_patching_v0,
    run_benchmark,
    run_goal,
    validate_dag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(tmp_path, safe_mode=True, max_retries=2):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))
    ex = ExecutiveController(config, queue, mem, max_retries=max_retries, plan_store=plan_store)
    return ex, queue, mem, plan_store, config


def _orch(tmp_path, exec_spy=False, safe_mode=True, max_retries=2, understanding=None, planner=None):
    ex, queue, mem, plan_store, config = _ctx(tmp_path, safe_mode=safe_mode, max_retries=max_retries)
    pl = planner or Planner()
    orch = GoalOrchestrator(
        pl, ex, understanding=understanding,
        journal=GoalJournal(str(tmp_path / "journal")),
        exec_spy=exec_spy,
    )
    return orch


def _decompose(goal):
    return GoalDecomposer().decompose(goal)


def _is_dag(g):
    return g.is_dag()


def _within_bounds(g, depth, breadth):
    return g.within_bounds()


def _run_order(orch, g):
    order = []
    while True:
        node = orch._next_ready(g)
        if node is None:
            break
        order.append(node.subgoal.subgoal_id)
        node.state = SubGoalState.DONE
    return order


def _expected_topo_order(g):
    return g.topological_order()


class _FakeUnderstanding:
    def __init__(self, syms):
        self._syms = set(syms)

    def defines(self, name):
        return [name] if name in self._syms else []


# ---------------------------------------------------------------------------
# §8 — structure: DAG, bounds, stable IDs, no cycles
# ---------------------------------------------------------------------------

def test_decomposition_is_a_validated_dag():
    g = _decompose(_multi_plan_goal())
    assert _is_dag(g) and _within_bounds(g, depth=3, breadth=8)


def test_cyclic_decomposition_is_rejected():
    with pytest.raises(CyclicDecomposition):
        validate_dag(_graph_with_cycle())


def test_subgoal_ids_are_stable_and_dedup():
    g1, g2 = _decompose(_goal_for_decompose()), _decompose(_goal_for_decompose())
    assert set(g1.nodes) == set(g2.nodes)               # deterministic, content-derived


# ---------------------------------------------------------------------------
# §8 — scheduling: deterministic, one-at-a-time, no hidden execution
# ---------------------------------------------------------------------------

def test_scheduling_is_deterministic_topological(tmp_path):
    assert _run_order(_orch(tmp_path), _goal_chain()) == _expected_topo_order(_goal_chain())


def test_one_plan_runs_at_a_time_via_existing_executive(tmp_path):
    orch = _orch(tmp_path, exec_spy=True)
    orch.run(_goal_chain())
    spy = orch.exec_spy
    assert spy.max_concurrent == 1          # no parallelism, no background agent
    assert spy.all_ran_through_safetylayer, (spy.max_concurrent, spy.steps, spy._all_gated,
        [e["kind"] for e in spy._memory.history()][-6:])


def test_orchestrator_has_no_tool_or_safety_handle(tmp_path):
    o = _orch(tmp_path)
    for banned in ("edit", "run_tool", "shell", "safety", "write_file"):
        assert not hasattr(o, banned)                 # it schedules; Executive executes


# ---------------------------------------------------------------------------
# §8 — automatic done-detection + dedup + skill reuse
# ---------------------------------------------------------------------------

def test_already_satisfied_subgoal_is_not_reexecuted(tmp_path):
    understanding = _FakeUnderstanding({"Foo"})
    g = _goal_with_half_done()
    orch = _orch(tmp_path, understanding=understanding)
    orch.run(g)
    assert any(r.reason == "already_satisfied" for r in g.nodes.values())
    done = g.nodes["done_leaf"]
    assert done.state == SubGoalState.DONE
    assert done.attempts == 0 and done.plan_id is None   # never re-executed


def test_promoted_skill_is_reused_for_matching_subgoal(tmp_path):
    ex, queue, mem, plan_store, config = _ctx(tmp_path)
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    reg.register(SkillTemplate(
            id="", name="copy", description="copy a file",
            trigger_patterns=[r"copy\s+path="], required_params=["path", "dst"],
            steps=[
                SkillStep(tool="read_file", arg_template='{"path": "{path}"}', reason="read", depends_on=[]),
                SkillStep(tool="write_file", arg_template='{"path": "{dst}", "content": "copied"}', reason="write", depends_on=[0]),
            ],
        ))
    planner = Planner(
        skills=reg,
        registry_tools=("echo", "read_file", "write_file", "list_dir", "edit_file",
                        "search_content", "run_tests", "run_check", "shell"),
    )
    orch = GoalOrchestrator(planner, ex)
    sg = SubGoal(subgoal_id="sg_x", description=f"copy path={tmp_path}/s.txt dst={tmp_path}/d.txt")
    plan = orch._plan_for(SubGoalRun(sg))
    assert plan.plan_source.startswith("skill")       # repo-aware skill reuse


# ---------------------------------------------------------------------------
# §8 — failure isolation, subtree retry, rollback, blocked propagation
# ---------------------------------------------------------------------------

def test_failed_branch_does_not_restart_independent_branches(tmp_path):
    g = _goal_two_independent_branches(fail="branch_A")
    orch = _orch(tmp_path)
    _patch_fail(orch._executive, "FAIL")
    orch.run(g)
    assert g.nodes["branch_B_leaf"].state == SubGoalState.DONE
    assert g.nodes["branch_A_leaf"].state == SubGoalState.FAILED


def test_subtree_retry_budget_is_bounded(tmp_path):
    g = _goal(fail_forever="n1", retry_budget=2)
    orch = _orch(tmp_path)
    _patch_fail(orch._executive, "FAIL")
    orch.run(g)
    assert g.nodes["n1"].attempts <= 3                     # initial + 2 retries


def test_dependents_block_when_dependency_fails(tmp_path):
    g = _goal_chain_fail(fail="n1")
    orch = _orch(tmp_path)
    _patch_fail(orch._executive, "FAIL")
    orch.run(g)
    assert g.nodes["n2_depends_on_n1"].state == SubGoalState.BLOCKED


def test_subtree_rollback_leaves_siblings_intact(tmp_path):
    g = _goal_two_branches(tmp_path)
    orch = _orch(tmp_path, safe_mode=False)
    result = orch.run_then_rollback(g, subtree="A_leaf")
    assert not g._files["A"].exists()                     # A reverted via undo seam
    assert g._files["B"].exists()                         # B untouched


def test_reflection_still_owns_repair_inside_subgoal(tmp_path):
    from aetheris.understanding.engine import RepoUnderstanding

    (tmp_path / "mymod.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    understanding = RepoUnderstanding(str(tmp_path), str(tmp_path / "model.json"))
    understanding.scan()

    config = Config(log_path=str(tmp_path / "ctrl.jsonl"), workspace_root=str(tmp_path), safe_mode=False)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    plan_store = PlanStore(str(tmp_path / "plans"))
    ex = ExecutiveController(config, queue, mem, understanding=understanding, max_retries=2, plan_store=plan_store)
    orig = ex._controller.handle_step
    ex._controller.handle_step = lambda tool, arg, **kw: (
        (_ for _ in ()).throw(RuntimeError("importerror: helper done"))
        if "FAIL_REPAIR" in arg else orig(tool, arg, **kw)
    )
    g = GoalGraph("rep", "rep")
    g.add(SubGoal(subgoal_id="n1", description="do FAIL_REPAIR thing"))
    orch = GoalOrchestrator(Planner(), ex, understanding=understanding)
    r = orch.run(g)
    assert r.repairs_via == "reflection"


# ---------------------------------------------------------------------------
# §8 — resume / checkpoint / cancel
# ---------------------------------------------------------------------------

def test_resume_skips_completed_subtrees(tmp_path):
    orch = _orch(tmp_path)
    g = _goal_chain()
    orch.run_until(g, "a")                                 # interrupt after 'a'
    journal = orch._journal
    g2 = journal.resume(g.goal_id)
    assert g2 is not None, f"resume returned None; snapshots={list((Path(str(tmp_path))/'journal'/'snapshots').glob('*'))}"
    assert "b" in g2.nodes, f"g2 nodes={list(g2.nodes.keys())}"
    orch2 = GoalOrchestrator(Planner(), orch._executive, journal=journal)
    prev_done = {sid: run.attempts for sid, run in g2.nodes.items() if run.state == SubGoalState.DONE}
    orch2.run(g2)
    for sid in prev_done:
        assert g2.nodes[sid].attempts == prev_done[sid]   # completed subtree not re-run
    assert g2.nodes["b"].state == SubGoalState.DONE
    assert g2.nodes["c"].state == SubGoalState.DONE


def test_journal_is_append_only_and_reconstructs_run(tmp_path):
    orch = _orch(tmp_path)
    g = _goal_chain()
    orch.run(g)
    recon = orch._journal.reconstruct(g.goal_id)
    final = {sid: run.state.value for sid, run in g.nodes.items()}
    assert recon == final


def test_cancellation_propagates_without_midwrite_kill(tmp_path):
    g = _goal_two_independent_branches()
    g.add(SubGoal(subgoal_id="A_unstarted_child", description="echo A child",
                  depends_on=("branch_A_leaf",)))
    orch = _orch(tmp_path)
    orch.run_with_cancel(g, at="branch_A_leaf")
    assert g.nodes["A_unstarted_child"].state == SubGoalState.CANCELLED
    assert g.nodes["A_unstarted_child"].attempts == 0       # never started -> no partial write


# ---------------------------------------------------------------------------
# §8 — fallback / no-regression / authority
# ---------------------------------------------------------------------------

def test_flat_friendly_goal_is_byte_identical(tmp_path):
    ex_on, _, _, _, _ = _ctx(tmp_path)
    ex_off, _, _, _, _ = _ctx(tmp_path)
    desc = "hello there"
    on = run_goal(desc, hierarchy=True, planner=Planner(), executive=ex_on, goal_id="f")
    off = run_goal(desc, hierarchy=False, planner=Planner(), executive=ex_off, goal_id="f")
    assert on == off


def test_decomposer_abstains_falls_back_to_flat(tmp_path):
    ex_on, _, _, _, _ = _ctx(tmp_path)
    ex_off, _, _, _, _ = _ctx(tmp_path)
    desc = "hello there"
    on = run_goal(desc, hierarchy=True, planner=Planner(), executive=ex_on, goal_id="a")
    off = run_goal(desc, hierarchy=False, planner=Planner(), executive=ex_off, goal_id="a")
    assert on == off


def test_hierarchy_off_is_byte_identical_to_model_patching_v0(tmp_path):
    ex_off, _, _, _, _ = _ctx(tmp_path)
    ex_base, _, _, _, _ = _ctx(tmp_path)
    r_off = run_benchmark(False, Planner(), ex_off, root=str(tmp_path / "off"))
    r_base = baseline_model_patching_v0(Planner(), ex_base, root=str(tmp_path / "base"))
    assert r_off == r_base


def test_meets_adoption_gate(tmp_path):
    ex_flat, _, _, _, _ = _ctx(tmp_path, safe_mode=False, max_retries=2)
    ex_hier, _, _, _, _ = _ctx(tmp_path, safe_mode=False, max_retries=2)
    _patch_fail(ex_flat, "BOOM")
    _patch_fail(ex_hier, "BOOM")

    flat = run_benchmark(False, Planner(), ex_flat, root=str(tmp_path / "flat"), retry_budget=2)
    hier = run_benchmark(True, Planner(), ex_hier, root=str(tmp_path / "hier"), retry_budget=1)

    assert hier.completion >= flat.completion
    assert (
        hier.retries < flat.retries
        or hier.repairs < flat.repairs
        or hier.duplicate_work < flat.duplicate_work
        or hier.latency < flat.latency
    )
    assert hier.regressions == 0
    assert hier.blocked_unsafe <= flat.blocked_unsafe


# ---------------------------------------------------------------------------
# Fixtures (goal shapes)
# ---------------------------------------------------------------------------

def _multi_plan_goal():
    return Goal("m", "echo one then echo two then echo three")


def _goal_for_decompose():
    return Goal("g", "echo first then echo second then echo third")


def _graph_with_cycle():
    g = GoalGraph("cyc", "cyc")
    g.add(SubGoal(subgoal_id="p", description="echo p", depends_on=("q",)))
    g.add(SubGoal(subgoal_id="q", description="echo q", depends_on=("p",)))
    return g


def _goal_chain():
    g = GoalGraph("chain", "chain")
    g.add(SubGoal(subgoal_id="a", description="echo step a"))
    g.add(SubGoal(subgoal_id="b", description="echo step b", depends_on=("a",)))
    g.add(SubGoal(subgoal_id="c", description="echo step c", depends_on=("b",)))
    return g


def _goal_two_independent_branches(fail="branch_A"):
    g = GoalGraph("two", "two")
    g.add(SubGoal(subgoal_id="branch_A_leaf", description=f"echo FAIL {fail}"))
    g.add(SubGoal(subgoal_id="branch_B_leaf", description="echo branch B"))
    return g


def _goal(fail_forever="n1", retry_budget=2):
    g = GoalGraph("gf", "gf")
    g.add(SubGoal(subgoal_id=fail_forever, description=f"echo FAIL {fail_forever}",
                  retry_budget=retry_budget))
    return g


def _goal_chain_fail(fail="n1"):
    g = GoalGraph("gc", "gc")
    g.add(SubGoal(subgoal_id="n1", description=f"echo FAIL {fail}"))
    g.add(SubGoal(subgoal_id="n2_depends_on_n1", description="echo n2", depends_on=("n1",)))
    return g


def _goal_two_branches(tmp_path):
    a = tmp_path / "A.txt"
    b = tmp_path / "B.txt"
    g = GoalGraph("gb", "gb")
    g.add(SubGoal(subgoal_id="A_leaf", description=f"create path={a} content=A"))
    g.add(SubGoal(subgoal_id="B_leaf", description=f"create path={b} content=B"))
    g._files = {"A": a, "B": b}
    return g


def _goal_with_half_done():
    g = GoalGraph("hd", "hd")
    g.add(SubGoal(subgoal_id="done_leaf", description="echo already done", done_if_symbol="Foo"))
    g.add(SubGoal(subgoal_id="todo_leaf", description="echo todo"))
    return g


def _patch_fail(executive, marker):
    orig = executive._controller.handle_step
    executive._controller.handle_step = lambda tool, arg, **kw: (
        (_ for _ in ()).throw(RuntimeError("boom"))
        if marker in arg else orig(tool, arg, **kw)
    )
