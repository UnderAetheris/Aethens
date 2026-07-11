"""Idle-Time Skill Promotion v0 — 10 tests per spec §5.

   1.  test_promotion_runs_only_when_idle          — work present -> mined=0
   2.  test_promotion_fires_after_idle_threshold   — N idle ticks -> mined>=1
   3.  test_work_arriving_preempts_promotion       — idle_promotion_yielded
   4.  test_budget_limits_candidates_per_cycle     — tried==1 with budget=1
   5.  test_accepted_promotion_is_journaled_and_registered
   6.  test_rejected_promotion_is_journaled_with_reason
   7.  test_no_candidates_leaves_system_unchanged
   8.  test_live_task_latency_unaffected           — continuous work, mined=0
   9.  test_restart_explainability                 — journal reconstructs cycle
  10.  test_promotion_off_by_default_is_todays_behavior
"""
from __future__ import annotations

import time

from aetheris.config import Config
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue
from aetheris.learning.engine import LearningEngine
from aetheris.memory.experience import ExperienceStore
from aetheris.memory.knowledge import KnowledgeStore
from aetheris.memory.learned import LearnedKeywordStore
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.skills.idle_promotion import IdleSkillPromotion
from aetheris.skills.promoter import SkillCandidate, SkillStep
from aetheris.skills.registry import SkillRegistry


# ===========================================================================
# Helpers
# ===========================================================================

def _make_executive(tmp_path, skill_promotion=None, promotion_budget=1, improve_fn=None):
    if improve_fn is None:
        def improve_fn():
            return False

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
    )
    return (
        ExecutiveController(
            config, queue, mem,
            improve_fn=improve_fn,
            skill_promotion=skill_promotion,
            promotion_budget=promotion_budget,
        ),
        queue,
        mem,
    )


def _reach_idle(ex, queue, ticks=3):
    for _ in range(ticks):
        ex.run_once()


def _make_promoter_with_candidates(n=3):
    class SpyPromoter:
        def __init__(self):
            self.candidates_list = [
                SkillCandidate(
                    name=f"auto_skill_{i}",
                    trigger=r"auto\s+skill",
                    params=(),
                    steps=(
                        SkillStep(tool="echo", arg_template='"ok"', reason="echo", depends_on=[]),
                    ),
                    provenance={"recurrence": n},
                )
                for i in range(n)
            ]

        def candidates(self, plans, memory=None):
            return self.candidates_list

    return SpyPromoter()


def _make_gate_false_comp(tmp_path):
    class GateFalse:
        def run(self, cases, skill=None):
            from aetheris.evaluation.compare import SkillComparisonResult, SkillCaseResult
            return SkillComparisonResult(
                baseline=[SkillCaseResult(name="wf", completed=True)],
                candidate=[SkillCaseResult(name="wf", completed=False)],
            )

    return GateFalse()


def _make_gate_true_comp(tmp_path):
    class GateTrue:
        def run(self, cases, skill=None):
            from aetheris.evaluation.compare import SkillComparisonResult, SkillCaseResult
            return SkillComparisonResult(
                baseline=[SkillCaseResult(name="wf", completed=True)],
                candidate=[SkillCaseResult(name="wf", completed=True)],
            )

    return GateTrue()


def _write_plans(tmp_path, n=3):
    ps = PlanStore(str(tmp_path / "plans"))
    for i in range(n):
        plan = MultiStepPlan(
            task_id=f"p{i}",
            steps=[PlanStep(tool="echo", arg='"ok"', reason="echo", depends_on=[])],
            created_at=time.time(),
        )
        for s in plan.steps:
            s.status = StepStatus.DONE
            s.output = "ok"
        ps.save(plan)


def _make_history_provider(tmp_path):
    ps = PlanStore(str(tmp_path / "plans"))
    _write_plans(tmp_path)
    return lambda: list(ps._dir.glob("*.plan.json"))


# ===========================================================================
# 1.  Promotion runs only when idle
# ===========================================================================

def test_promotion_runs_only_when_idle(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    queue.enqueue("hello")
    ex.run_once()
    assert promo.mined == 0


# ===========================================================================
# 2.  Promotion fires after idle threshold
# ===========================================================================

def test_promotion_fires_after_idle_threshold(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    _reach_idle(ex, queue, ticks=3)
    assert promo.mined >= 1
    kinds = [e["kind"] for e in mem.history()]
    assert "idle_promotion_started" in kinds


# ===========================================================================
# 3.  Work arriving preempts promotion
# ===========================================================================

def test_work_arriving_preempts_promotion(tmp_path):
    class PreemptingPromotion:
        def __init__(self, executive):
            self._ex = executive

        def candidates(self, completed, memory=None):
            # Enqueue work directly into the executive's queue.
            self._ex._queue.enqueue("preempt_me")
            return [SkillCandidate(
                name="preempt_me",
                trigger=r"preempt",
                params=(),
                steps=(SkillStep(tool="echo", arg_template='"ok"', reason="echo", depends_on=[]),),
                provenance={"recurrence": 3},
            )]

    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    ex, q, _ = _make_executive(tmp_path, skill_promotion=None)
    promo = IdleSkillPromotion(
        PreemptingPromotion(ex), reg, learning, comp, mem, str(tmp_path), lambda: []
    )
    ex._skill_promotion = promo

    # Reach idle threshold — promotion fires, mine() enqueues work,
    # loop detects it and yields.
    ex.run_once()  # idle tick 1
    ex.run_once()  # idle tick 2
    ex.run_once()  # idle tick 3 -> _on_idle -> _run_idle_promotion -> mine() enqueues -> yield

    kinds = [e["kind"] for e in mem.history()]
    assert "idle_promotion_yielded" in kinds


# ===========================================================================
# 4.  Budget limits candidates per cycle
# ===========================================================================

def test_budget_limits_candidates_per_cycle(tmp_path):
    spy = _make_promoter_with_candidates(n=5)
    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history,
                                promotion_budget=1)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo, promotion_budget=1)
    _reach_idle(ex, queue, ticks=3)
    assert promo.tried == 1


# ===========================================================================
# 5.  Accepted promotion is journaled and registered
# ===========================================================================

def test_accepted_promotion_is_journaled_and_registered(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_true_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    _reach_idle(ex, queue, ticks=3)

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promoted" in kinds
    active = [s.name for s in reg.active_skills()]
    assert "auto_skill_0" in active


# ===========================================================================
# 6.  Rejected promotion is journaled with reason
# ===========================================================================

def test_rejected_promotion_is_journaled_with_reason(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    _reach_idle(ex, queue, ticks=3)

    rej = [e for e in mem.history() if e["kind"] == "skill_promotion_rejected"]
    assert rej
    assert "reason" in rej[-1]["data"]


# ===========================================================================
# 7.  No candidates leaves system unchanged
# ===========================================================================

def test_no_candidates_leaves_system_unchanged(tmp_path):
    class NoCandidates:
        def candidates(self, plans, memory=None):
            return []

    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    promo = IdleSkillPromotion(NoCandidates(), reg, learning, comp, mem, str(tmp_path), lambda: [])

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    before = list(reg.active_skills())
    _reach_idle(ex, queue, ticks=3)
    after = list(reg.active_skills())
    assert after == before


# ===========================================================================
# 8.  Live task latency unaffected (continuous work)
# ===========================================================================

def test_live_task_latency_unaffected(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_false_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    for i in range(5):
        queue.enqueue(f"hello {i}")
    ex.drain()

    assert promo.mined == 0
    kinds = [e["kind"] for e in mem.history()]
    assert "idle_promotion_started" not in kinds


# ===========================================================================
# 9.  Restart explainability — journal reconstructs what/why
# ===========================================================================

def test_restart_explainability(tmp_path):
    spy = _make_promoter_with_candidates(n=3)
    comp = _make_gate_true_comp(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    learning = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )
    history = _make_history_provider(tmp_path)
    promo = IdleSkillPromotion(spy, reg, learning, comp, mem, str(tmp_path), history)

    ex, queue, _ = _make_executive(tmp_path, skill_promotion=promo)
    _reach_idle(ex, queue, ticks=3)

    kinds = [e["kind"] for e in mem.history()]
    assert "idle_promotion_started" in kinds

    skill_events = [e for e in mem.history() if e["kind"] == "skill_candidate_mined"]
    assert skill_events
    assert "provenance" in skill_events[-1]["data"]

    promoted_events = [e for e in mem.history() if e["kind"] == "skill_promoted"]
    assert promoted_events
    assert "version" in promoted_events[-1]["data"]


# ===========================================================================
# 10.  Promotion off by default is today's behavior
# ===========================================================================

def test_promotion_off_by_default_is_todays_behavior(tmp_path):
    ex, queue, mem = _make_executive(tmp_path, skill_promotion=None)
    _reach_idle(ex, queue, ticks=3)
    kinds = [e["kind"] for e in mem.history()]
    assert "idle_promotion_started" not in kinds
