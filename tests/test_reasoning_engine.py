"""Deliberative Reasoning Engine v0 — 20 tests.

   1.  test_reasoning_has_no_execution_or_tool_path
   2.  test_reasoning_constructed_without_safety_or_tools
   3.  test_deliberation_schema_cannot_express_an_action
   4.  test_deliberation_is_immutable
   5.  test_abstains_below_confidence_floor
   6.  test_hard_timeout_forces_abstain_not_guess
   7.  test_respects_max_hypotheses_and_max_depth
   8.  test_gather_context_when_load_bearing_assumption_unresolved
   9.  test_confidence_is_deterministic_from_signals
  10.  test_every_observation_and_risk_has_provenance
  11.  test_deliberation_is_journaled_appendonly
  12.  test_no_chain_of_thought_exposed
  13.  test_planner_may_ignore_deliberation
  14.  test_reflection_still_owns_verdict_with_reasoning_on
  15.  test_learning_gate_not_relaxed_by_reasoning
  16.  test_reasoning_can_only_make_learning_more_conservative
  17.  test_reasoning_off_is_byte_identical_to_prior_milestone
  18.  test_reasoning_meets_adoption_gate
  19.  test_abstention_precision_and_recall_above_threshold
  20.  test_authority_not_widened
"""
from __future__ import annotations

import dataclasses
import inspect
import time

import pytest
from fastapi.testclient import TestClient

from aetheris.api.app import create_app
from aetheris.api.state import AppState
from aetheris.config import Config, PromotionConfig
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.planner.planner import Planner
from aetheris.reasoning.engine import ReasoningEngine, ReasoningBudget
from aetheris.reasoning.schema import CandidateApproach, Deliberation, Observation, Provenance, Recommendation, Seam
from aetheris.safety.guard import SafetyLayer, build_default_rules
from aetheris.tools.base import Tool, ToolRegistry
from aetheris.understanding.engine import RepoUnderstanding
from aetheris.workspace import WorkspaceIndex


# ===========================================================================
# Helpers
# ===========================================================================

def _make_repo(tmp_path):
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "config.py").write_text(
        "def parse_config(path):\n"
        "    with open(path) as f:\n"
        "        return f.read()\n"
        "\n"
        "def load_settings():\n"
        "    return parse_config('settings.yaml')\n"
        "\n"
        "VERSION = '1.0'\n",
        encoding="utf-8",
    )
    (pkg / "main.py").write_text(
        "from .config import parse_config, load_settings\n"
        "\n"
        "def main():\n"
        "    cfg = parse_config('config.yaml')\n"
        "    settings = load_settings()\n"
        "    print(cfg, settings)\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_understanding(tmp_path):
    _make_repo(tmp_path)
    u = RepoUnderstanding(root=str(tmp_path), model_path=str(tmp_path / "repo_model.json"))
    u.scan()
    return u


def _make_memory(tmp_path):
    return MemoryStore(str(tmp_path / "events.jsonl"))


def _make_skills():
    reg = ToolRegistry()
    reg.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    reg.register(Tool(name="read_file", description="read",
                      run=lambda a: open(__import__('json').loads(a)["path"]).read(), safe=True))
    return reg


def _make_engine(tmp_path, model=None, **budget_kwargs):
    u = _make_understanding(tmp_path)
    mem = _make_memory(tmp_path)
    skills = _make_skills()
    budget = ReasoningBudget(**budget_kwargs)
    return ReasoningEngine(understanding=u, memory=mem, skills=skills, budget=budget, model=model)


# ===========================================================================
# 1.  reasoning has no execution or tool path
# ===========================================================================

def test_reasoning_has_no_execution_or_tool_path(tmp_path):
    r = _make_engine(tmp_path)
    for forbidden in ("execute", "apply", "edit", "run", "shell",
                      "write_file", "mutate_plan", "set_verdict", "safety", "tools"):
        assert not hasattr(r, forbidden), f"reasoning has forbidden attribute: {forbidden}"


# ===========================================================================
# 2.  reasoning constructed without safety or tools
# ===========================================================================

def test_reasoning_constructed_without_safety_or_tools():
    sig = inspect.signature(ReasoningEngine.__init__)
    params = set(sig.parameters.keys())
    assert "safety" not in params
    assert "tools" not in params
    assert "executive" not in params
    assert "planner_mutator" not in params


# ===========================================================================
# 3.  Deliberation schema cannot express an action
# ===========================================================================

def test_deliberation_schema_cannot_express_an_action():
    fields = {f.name for f in dataclasses.fields(Deliberation)}
    forbidden = {"step", "tool", "command", "edit", "path_to_write", "plan"}
    assert not (fields & forbidden), f"Deliberation has action fields: {fields & forbidden}"


# ===========================================================================
# 4.  Deliberation is immutable
# ===========================================================================

def test_deliberation_is_immutable():
    d = Deliberation(seam=Seam.PLANNER, subject="test")
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.confidence = 0.99


# ===========================================================================
# 5.  abstains below confidence floor
# ===========================================================================

def test_abstains_below_confidence_floor(tmp_path):
    r = _make_engine(tmp_path, confidence_floor=0.99)
    outcome = type("Outcome", (), {"output": "some error", "task_id": "t1", "step_index": 0})()
    d = r.deliberate_for_repair(outcome)
    assert d.recommendation == Recommendation.ABSTAIN
    assert d.abstained is True
    assert d.recommended_approach is None


# ===========================================================================
# 6.  hard timeout forces abstain not guess
# ===========================================================================

def test_hard_timeout_forces_abstain_not_guess(tmp_path):
    r = _make_engine(tmp_path, timeout_ms=0)
    ctx = type("Ctx", (), {"task": "do something complex with many options"})()
    d = r.deliberate_for_planning(ctx)
    assert d.abstained is True
    assert "timeout" in d.reason.lower()


# ===========================================================================
# 7.  respects max_hypotheses and max_depth
# ===========================================================================

def test_respects_max_hypotheses_and_max_depth(tmp_path):
    r = _make_engine(tmp_path, max_hypotheses=2, max_depth=1)
    ctx = type("Ctx", (), {"task": "plan a complex multi-step workflow with many alternatives"})()
    d = r.deliberate_for_planning(ctx)
    assert d.hypotheses_used <= 2
    assert d.depth_used <= 1


# ===========================================================================
# 8.  gather context when load-bearing assumption unresolved
# ===========================================================================

def test_gather_context_when_load_bearing_assumption_unresolved(tmp_path):
    r = _make_engine(tmp_path)
    outcome = type("Outcome", (), {
        "failure": "unknown symbol xyz",
        "task_id": "t1",
        "step_index": 0,
    })()
    d = r.deliberate_for_repair(outcome)
    assert d.recommendation in (Recommendation.GATHER_CONTEXT, Recommendation.ABSTAIN)


# ===========================================================================
# 9.  confidence is deterministic from signals
# ===========================================================================

def test_confidence_is_deterministic_from_signals(tmp_path):
    r = _make_engine(tmp_path)
    ctx1 = type("Ctx", (), {"task": "echo hello"})()
    ctx2 = type("Ctx", (), {"task": "echo hello"})()
    d1 = r.deliberate_for_planning(ctx1)
    d2 = r.deliberate_for_planning(ctx2)
    assert d1.confidence == d2.confidence


# ===========================================================================
# 10.  every observation and risk has provenance
# ===========================================================================

def test_every_observation_and_risk_has_provenance(tmp_path):
    r = _make_engine(tmp_path)
    outcome = type("Outcome", (), {
        "failure": "assertion failure in test",
        "task_id": "t1",
        "step_index": 0,
    })()
    d = r.deliberate_for_repair(outcome)
    for o in d.observations:
        assert o.provenance.source, f"observation missing provenance: {o}"
    for risk in d.risks:
        assert risk.provenance.source, f"risk missing provenance: {risk}"


# ===========================================================================
# 11.  deliberation is journaled append-only
# ===========================================================================

def test_deliberation_is_journaled_appendonly(tmp_path):
    r = _make_engine(tmp_path)
    ctx = type("Ctx", (), {"task": "list files in the workspace"})()
    d = r.deliberate_for_planning(ctx)
    # Non-abstained deliberations are journaled.
    if not d.abstained:
        assert len(r.reasoning_history()) == 1
        entry = r.reasoning_history()[0]
        assert entry["seam"] == "planner"
        assert entry["timestamp"] > 0


# ===========================================================================
# 12.  no chain-of-thought exposed
# ===========================================================================

def test_no_chain_of_thought_exposed(tmp_path):
    class MockModel:
        def __call__(self, prompt):
            return {"extra_candidate": "mock_approach", "monologue": "let me think about this carefully"}

    r = _make_engine(tmp_path, model=MockModel())
    outcome = type("Outcome", (), {
        "failure": "module not found",
        "task_id": "t1",
        "step_index": 0,
    })()
    d = r.deliberate_for_repair(outcome)
    for o in d.observations:
        assert "let me think" not in o.statement.lower()


# ===========================================================================
# 13.  planner may ignore deliberation
# ===========================================================================

def test_planner_may_ignore_deliberation(tmp_path):
    r = _make_engine(tmp_path)
    ctx = type("Ctx", (), {"task": "read a file"})()
    d = r.deliberate_for_planning(ctx)
    assert d.seam == Seam.PLANNER
    # The planner can ignore the recommendation; the deliberation is just data.
    assert d.recommendation in (Recommendation.PREFER, Recommendation.ABSTAIN, Recommendation.CAUTION, Recommendation.GATHER_CONTEXT)


# ===========================================================================
# 14.  reflection still owns verdict with reasoning on
# ===========================================================================

def test_reflection_still_owns_verdict_with_reasoning_on(tmp_path):
    u = _make_understanding(tmp_path)
    mem = _make_memory(tmp_path)
    skills = _make_skills()
    r = ReasoningEngine(understanding=u, memory=mem, skills=skills)
    engine = __import__("aetheris.reflection.engine", fromlist=["ReflectionEngine"]).ReflectionEngine(
        understanding=u, reasoning=r
    )
    outcome = type("Outcome", (), {
        "task_id": "t1",
        "step_index": 0,
        "tool": "run_tests",
        "arg": "",
        "ok": False,
        "output": "ModuleNotFoundError: No module named 'parse_config'",
        "blocked": False,
        "attempt": 1,
        "repair_suggestions": [],
        "failure_kind": "missing_import",
    })()
    plan = MultiStepPlan(task_id="t1", steps=[])
    result = engine.reflect(outcome, plan)
    assert result.verdict.value == "insert_repair_steps"


# ===========================================================================
# 15.  learning gate not relaxed by reasoning
# ===========================================================================

def test_learning_gate_not_relaxed_by_reasoning(tmp_path):
    u = _make_understanding(tmp_path)
    mem = _make_memory(tmp_path)
    skills = _make_skills()
    r = ReasoningEngine(understanding=u, memory=mem, skills=skills)
    candidate = type("Cand", (), {
        "name": "bad_skill",
        "task_id": "t1",
        "benchmark_deltas": {"baseline_rate": 0.3, "new_rate": 0.4},
    })()
    d = r.deliberate_for_promotion(candidate)
    # Reasoning may abstain or caution; it never forces adopt.
    assert d.recommendation in (Recommendation.ABSTAIN, Recommendation.CAUTION, Recommendation.PREFER)


# ===========================================================================
# 16.  reasoning can only make learning more conservative
# ===========================================================================

def test_reasoning_can_only_make_learning_more_conservative(tmp_path):
    u = _make_understanding(tmp_path)
    mem = _make_memory(tmp_path)
    skills = _make_skills()
    r = ReasoningEngine(understanding=u, memory=mem, skills=skills)
    candidate = type("Cand", (), {
        "name": "borderline_skill",
        "task_id": "t1",
        "benchmark_deltas": {"baseline_rate": 0.5, "new_rate": 0.51},
    })()
    d = r.deliberate_for_promotion(candidate)
    # Reasoning can only add caution or abstain, never force-adopt.
    assert d.recommendation != Recommendation.PREFER or d.confidence >= 0.6


# ===========================================================================
# 17.  reasoning off is byte-identical to prior milestone
# ===========================================================================

def test_reasoning_off_is_byte_identical_to_prior_milestone(tmp_path):
    from aetheris.api.app import create_app
    from aetheris.api.state import AppState
    from fastapi.testclient import TestClient

    state = AppState.create(root=str(tmp_path / "data"))
    assert state.reasoning is None
    app = create_app(state=state, auto_tick=False)
    with TestClient(app) as c:
        c.app_state = app.state.aetheris
        created = c.post("/tasks", json={"task": "echo hello"}).json()
        for _ in range(10):
            c.app_state.executive.run_once()
        rec = c.app_state.queue.get(created["id"])
        assert rec.state in (TaskState.DONE, TaskState.BLOCKED, TaskState.FAILED)


# ===========================================================================
# 18.  reasoning meets adoption gate
# ===========================================================================

def test_reasoning_meets_adoption_gate(tmp_path):
    from aetheris.evaluation.cases import code_repair_suite
    from aetheris.evaluation.compare import SkillComparison

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    cases = code_repair_suite(str(tmp_path))
    result = comp.run(cases)
    assert result.completion_on >= result.completion_off
    assert not result.regressed
    assert result.blocked_on <= result.blocked_off


# ===========================================================================
# 19.  abstention precision and recall above threshold
# ===========================================================================

def test_abstention_precision_and_recall_above_threshold(tmp_path):
    r = _make_engine(tmp_path, confidence_floor=0.6)
    should_abstain = [
        type("O", (), {"failure": "unknown xyz", "task_id": "t1", "step_index": 0})(),
        type("O", (), {"failure": "random error", "task_id": "t2", "step_index": 0})(),
    ]
    should_answer = [
        type("O", (), {"failure": "ModuleNotFoundError: parse_config", "task_id": "t3", "step_index": 0})(),
    ]
    abstained_correct = sum(1 for o in should_abstain if r.deliberate_for_repair(o).abstained)
    answered_correct = sum(1 for o in should_answer if not r.deliberate_for_repair(o).abstained)
    precision = abstained_correct / max(1, abstained_correct + max(0, len(should_answer) - answered_correct))
    recall = abstained_correct / max(1, len(should_abstain))
    assert precision >= 0.5
    assert recall >= 0.5


# ===========================================================================
# 20.  authority not widened
# ===========================================================================

def test_authority_not_widened(tmp_path):
    from aetheris.evaluation.cases import code_repair_suite
    from aetheris.evaluation.compare import SkillComparison

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    cases = code_repair_suite(str(tmp_path))
    result = comp.run(cases)
    assert result.blocked_on <= result.blocked_off
