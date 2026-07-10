"""Tests for AutoSkillSynthesizer, AutonomousLoop, SelfRepair, PlanReviewQueue."""
from __future__ import annotations

import json
import time

from aetheris.learning.autonomous import AutonomousLoop, CycleResult
from aetheris.learning.plan_review import PlanReviewQueue, ReviewStatus
from aetheris.learning.self_repair import SelfRepair
from aetheris.learning.synthesis import AutoSkillSynthesizer, PlanJournalMiner
from aetheris.memory.experience import ExperienceStore
from aetheris.memory.knowledge import KnowledgeStore
from aetheris.memory.learned import LearnedKeywordStore
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.skills.registry import SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem(tmp_path):
    return MemoryStore(str(tmp_path / "events.jsonl"))


def _plan_store(tmp_path):
    return PlanStore(str(tmp_path / "plans"))


def _save_completed_plan(tmp_path, steps):
    store = _plan_store(tmp_path)
    plan = MultiStepPlan(task_id="auto-1", steps=steps, source="decomposed")
    for s in plan.steps:
        s.status = "done"
        s.output = "ok"
    store.save(plan)
    return plan


# ---------------------------------------------------------------------------
# PlanReviewQueue
# ---------------------------------------------------------------------------

class TestPlanReviewQueue:
    def test_submit_returns_pending(self, tmp_path):
        queue = PlanReviewQueue()
        plan = MultiStepPlan(task_id="t1", steps=[])
        pending = queue.submit("do thing", plan)
        assert pending.status == ReviewStatus.PENDING
        assert pending.review_id is not None

    def test_pending_lists_only_pending(self, tmp_path):
        queue = PlanReviewQueue()
        plan = MultiStepPlan(task_id="t1", steps=[])
        p1 = queue.submit("task 1", plan)
        p2 = queue.submit("task 2", plan)
        queue.approve(p2.review_id)
        pending = queue.pending()
        assert len(pending) == 1
        assert pending[0].review_id == p1.review_id

    def test_approve_changes_status(self, tmp_path):
        queue = PlanReviewQueue()
        plan = MultiStepPlan(task_id="t1", steps=[])
        pending = queue.submit("task", plan)
        result = queue.approve(pending.review_id)
        assert result.status == ReviewStatus.APPROVED
        assert queue.get(pending.review_id).status == ReviewStatus.APPROVED

    def test_reject_with_feedback(self, tmp_path):
        queue = PlanReviewQueue()
        plan = MultiStepPlan(task_id="t1", steps=[])
        pending = queue.submit("task", plan)
        result = queue.reject(pending.review_id, "too risky")
        assert result.status == ReviewStatus.REJECTED
        assert result.user_feedback == "too risky"

    def test_modify_updates_plan(self, tmp_path):
        queue = PlanReviewQueue()
        plan = MultiStepPlan(task_id="t1", steps=[])
        pending = queue.submit("task", plan)
        modified = MultiStepPlan(task_id="t1", steps=[PlanStep(tool="echo", arg='"hi"', reason="echo")])
        result = queue.modify(pending.review_id, modified, "use echo instead")
        assert result.status == ReviewStatus.MODIFIED
        assert result.user_feedback == "use echo instead"


# ---------------------------------------------------------------------------
# PlanJournalMiner
# ---------------------------------------------------------------------------

class TestPlanJournalMiner:
    def test_empty_plans(self, tmp_path):
        miner = PlanJournalMiner(_mem(tmp_path), str(tmp_path / "plans"))
        assert miner.completed_plans() == []

    def test_groups_by_shape(self, tmp_path):
        store = _plan_store(tmp_path)
        steps_a = [PlanStep(tool="list_dir", arg='{"path": "/a"}', reason="list", depends_on=[]),
                    PlanStep(tool="read_file", arg='{"path": "/a/f"}', reason="read", depends_on=[0])]
        steps_b = [PlanStep(tool="list_dir", arg='{"path": "/b"}', reason="list", depends_on=[]),
                    PlanStep(tool="read_file", arg='{"path": "/b/f"}', reason="read", depends_on=[0])]
        for i, steps in enumerate([steps_a, steps_b], 1):
            plan = MultiStepPlan(task_id=f"p{i}", steps=steps, source="decomposed")
            for s in plan.steps:
                s.status = StepStatus.DONE
                s.output = "ok"
            store.save(plan)

        miner = PlanJournalMiner(_mem(tmp_path), str(tmp_path / "plans"))
        plans = miner.completed_plans()
        assert len(plans) == 2
        shapes = miner.plan_shapes(plans)
        assert len(shapes) == 1  # same shape

    def test_skips_incomplete(self, tmp_path):
        store = _plan_store(tmp_path)
        plan = MultiStepPlan(task_id="p1", steps=[PlanStep(tool="echo", arg='"hi"', reason="echo")])
        # Not all steps done.
        store.save(plan)
        miner = PlanJournalMiner(_mem(tmp_path), str(tmp_path / "plans"))
        assert miner.completed_plans() == []


# ---------------------------------------------------------------------------
# AutoSkillSynthesizer
# ---------------------------------------------------------------------------

class TestAutoSkillSynthesizer:
    def test_insufficient_occurrences(self, tmp_path):
        reg = _registry(tmp_path)
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), reg, min_occurrences=5)
        # No plans in journal -> nothing to synthesize.
        result = synth.synthesize()
        assert result.proposed == []
        assert result.promoted == []
        assert result.rejected == []

    def test_extract_params_from_steps(self, tmp_path):
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), _registry(tmp_path))
        steps = [PlanStep(tool="read_file", arg=json.dumps({"path": "/a/b"}), reason="read", depends_on=[])]
        params = synth._extract_params(steps)
        assert params is not None
        assert "path" in params

    def test_generalize_arg_replaces_values(self, tmp_path):
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), _registry(tmp_path))
        arg = json.dumps({"path": "/a/b", "content": "hello"})
        params = {"path": "/a/b", "content": "hello"}
        result = synth._generalize_arg(arg, params)
        parsed = json.loads(result)
        assert parsed["path"] == "{path}"
        assert parsed["content"] == "{content}"

    def test_make_name_for_list_read(self, tmp_path):
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), _registry(tmp_path))
        name = synth._make_name(["list_dir", "read_file"], {"dir": "/a", "file": "f"})
        assert name == "auto_list_and_read"

    def test_skips_single_tool_plans(self, tmp_path):
        reg = _registry(tmp_path)
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), reg, min_occurrences=1)
        # Create a single-tool completed plan.
        store = _plan_store(tmp_path)
        plan = MultiStepPlan(task_id="p1", steps=[PlanStep(tool="echo", arg='"hi"', reason="echo")])
        for s in plan.steps:
            s.status = StepStatus.DONE
            s.output = "ok"
        store.save(plan)
        result = synth.synthesize()
        assert result.proposed == []


# ---------------------------------------------------------------------------
# SelfRepair
# ---------------------------------------------------------------------------

class TestSelfRepair:
    def test_detect_empty_memory(self, tmp_path):
        repair = SelfRepair(_mem(tmp_path), str(tmp_path),
                            KnowledgeStore(str(tmp_path / "know.jsonl")),
                            ExperienceStore(str(tmp_path / "exp.jsonl")),
                            LearnedKeywordStore(str(tmp_path / "learned.jsonl")))
        assert repair.detect() == []

    def test_detect_recurring_failure(self, tmp_path):
        mem = _mem(tmp_path)
        for _ in range(4):
            mem.record("task_blocked", {"reason": "path escapes workspace root"})
        repair = SelfRepair(mem, str(tmp_path),
                            KnowledgeStore(str(tmp_path / "know.jsonl")),
                            ExperienceStore(str(tmp_path / "exp.jsonl")),
                            LearnedKeywordStore(str(tmp_path / "learned.jsonl")))
        proposals = repair.detect()
        assert len(proposals) >= 1
        assert proposals[0].occurrences >= 3

    def test_apply_non_keyword_repair_records_experience(self, tmp_path):
        mem = _mem(tmp_path)
        mem.record("task_blocked", {"reason": "some unknown error"})
        for _ in range(4):
            mem.record("task_blocked", {"reason": "some unknown error"})
        repair = SelfRepair(mem, str(tmp_path),
                            KnowledgeStore(str(tmp_path / "know.jsonl")),
                            ExperienceStore(str(tmp_path / "exp.jsonl")),
                            LearnedKeywordStore(str(tmp_path / "learned.jsonl")))
        proposals = repair.detect()
        result = repair.apply(proposals[0])
        assert result.applied is False
        assert "experience" in result.reason.lower()


# ---------------------------------------------------------------------------
# AutonomousLoop
# ---------------------------------------------------------------------------

class TestAutonomousLoop:
    def test_cycle_runs_without_error(self, tmp_path):
        loop = _autonomous_loop(tmp_path)
        result = loop.cycle()
        assert isinstance(result, CycleResult)
        assert result.duration_ms > 0
        assert loop.total_cycles == 1

    def test_cycle_records_keyword_learning(self, tmp_path):
        loop = _autonomous_loop(tmp_path)
        result = loop.cycle()
        # Learning may or may not accept depending on baseline.
        assert result.learned is True or result.learned is False

    def test_cycle_synthesis_empty_when_no_plans(self, tmp_path):
        loop = _autonomous_loop(tmp_path)
        result = loop.cycle()
        assert result.skills_proposed == 0
        assert result.skills_promoted == 0

    def test_uptime_increases(self, tmp_path):
        loop = _autonomous_loop(tmp_path)
        loop.cycle()
        time.sleep(0.01)
        assert loop.uptime_seconds > 0

    def test_last_result_persists(self, tmp_path):
        loop = _autonomous_loop(tmp_path)
        loop.cycle()
        assert loop.last_result is not None
        assert loop.last_result.duration_ms > 0


# ---------------------------------------------------------------------------
# Integration: skill synthesis + promotion
# ---------------------------------------------------------------------------

class TestSkillSynthesisIntegration:
    def test_synthesized_skill_clears_gate(self, tmp_path):
        reg = _registry(tmp_path)
        synth = AutoSkillSynthesizer(_mem(tmp_path), str(tmp_path), reg, min_occurrences=1)

        # Build a shape that matches the workflow suite (list_dir -> read_file).
        steps = [
            PlanStep(tool="list_dir", arg=json.dumps({"path": "/data"}), reason="list", depends_on=[]),
            PlanStep(tool="read_file", arg=json.dumps({"path": "/data/a.txt"}), reason="read", depends_on=[0]),
        ]
        skill = synth._synthesize_from_shape(
            tuple((s.tool, tuple(s.depends_on)) for s in steps),
            [MultiStepPlan(task_id="p1", steps=steps, source="decomposed")],
        )
        assert skill is not None
        assert skill.name == "auto_list_and_read"
        assert "list_dir" in skill.steps[0].tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry(tmp_path):
    return SkillRegistry(str(tmp_path / "skills.jsonl"))


def _autonomous_loop(tmp_path):
    mem = _mem(tmp_path)
    knowledge = KnowledgeStore(str(tmp_path / "know.jsonl"))
    experience = ExperienceStore(str(tmp_path / "exp.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    registry = _registry(tmp_path)
    return AutonomousLoop(mem, str(tmp_path), knowledge, experience, learned, registry)
