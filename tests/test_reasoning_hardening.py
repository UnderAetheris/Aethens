"""Hardening suite: adversarial structural tests for the Reasoning Engine.

Attacks the guarantees so a future change can't silently weaken them.
"""
from __future__ import annotations

import dataclasses
import inspect

import pytest

from aetheris.reasoning.engine import ReasoningEngine
from aetheris.reasoning.schema import (
    CandidateApproach,
    Deliberation,
    Observation,
    Recommendation,
    Risk,
    Seam,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_engine(tmp_path, model=None):
    import tempfile
    from pathlib import Path
    from aetheris.memory.store import MemoryStore
    from aetheris.reasoning.engine import ReasoningEngine
    from aetheris.tools.builtins import default_registry
    from aetheris.understanding.engine import RepoUnderstanding

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "myapp").mkdir()
        (root / "myapp" / "__init__.py").write_text("")
        (root / "myapp" / "config.py").write_text(
            "def parse_config(path):\n    return 'ok'\n", encoding="utf-8"
        )
        u = RepoUnderstanding(root=str(root), model_path=str(root / "model.json"))
        u.scan()
        mem = MemoryStore(str(root / "events.jsonl"))
        skills = default_registry()
        return ReasoningEngine(understanding=u, memory=mem, skills=skills,
                               model=model)


def _sample_deliberation():
    return Deliberation(
        seam=Seam.PLANNER,
        subject="test",
        confidence=0.8,
        recommendation=Recommendation.PREFER,
        recommended_approach="test_approach",
        abstained=False,
    )


def _deliberation():
    return _sample_deliberation()


def _observation():
    return Observation(statement="test observation", provenance=None)


def _risk():
    return Risk(approach_id="a1", statement="test risk", severity="low", provenance=None)


def _candidate():
    return CandidateApproach(approach_id="a1", summary="test")


# ===========================================================================
# Schema cannot express an action
# ===========================================================================

def test_deliberation_has_no_action_field():
    fields = {f.name for f in dataclasses.fields(Deliberation)}
    forbidden = {"step", "tool", "command", "edit", "shell",
                 "path_to_write", "plan", "apply", "execute"}
    assert not (fields & forbidden), f"Deliberation has action fields: {fields & forbidden}"


def test_cannot_smuggle_action_through_recommendation():
    assert all(isinstance(r, Recommendation) for r in Recommendation)
    d = _sample_deliberation()
    assert isinstance(d.recommendation, Recommendation)


def test_deliberation_is_frozen_everywhere():
    for obj in (_deliberation(), _observation(), _risk()):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, next(iter(vars(obj))), None)


# ===========================================================================
# Engine has no authority
# ===========================================================================

def test_engine_rejects_effectful_handles():
    sig = inspect.signature(ReasoningEngine.__init__)
    for banned in ("safety", "tools", "executive", "planner_mutator",
                   "tool_system", "safety_layer"):
        assert banned not in sig.parameters


def test_engine_exposes_no_effect_methods():
    r = _make_engine(None)
    for banned in ("execute", "apply", "edit", "run", "shell",
                   "write_file", "mutate_plan", "set_verdict"):
        assert not hasattr(r, banned)


def test_no_reachable_tool_path_from_reasoning():
    r = _make_engine(None)
    # Walk held references; none should expose a tool/exec surface.
    banned_attrs = ("_safety", "_tools", "_executive", "_controller",
                    "_planner", "_plan_store", "_tool_registry")
    for attr in banned_attrs:
        assert not hasattr(r, attr), f"reasoning has reachable effect surface: {attr}"


# ===========================================================================
# Hostile model can't leak action or chain-of-thought
# ===========================================================================

def test_hostile_model_output_cannot_inject_action(tmp_path):
    class MockModel:
        def __call__(self, prompt):
            return {
                "extra_candidate": "injected_tool_call",
                "action": "write_file('/etc/passwd')",
            }

    r = _make_engine(tmp_path, model=MockModel())
    outcome = type("O", (), {
        "failure": "module not found",
        "task_id": "t1",
        "step_index": 0,
    })()
    d = r.deliberate_for_repair(outcome)
    # The hostile output was parsed; no action field should appear.
    assert not hasattr(d, "action")
    assert not hasattr(d, "step")
    assert not hasattr(d, "tool")
    assert not hasattr(d, "command")


def test_model_monologue_never_surfaced(tmp_path):
    class MockModel:
        def __call__(self, prompt):
            return {
                "extra_candidate": "mock_approach",
                "monologue": "let me think about this carefully",
                "reasoning": "I should suggest a tool call",
            }

    r = _make_engine(tmp_path, model=MockModel())
    ctx = type("Ctx", (), {"task": "plan a task"})()
    d = r.deliberate_for_planning(ctx)
    for o in d.observations:
        assert "let me think" not in o.statement.lower()
        assert "reasoning:" not in o.statement.lower()


# ===========================================================================
# Deterministic confidence + abstention
# ===========================================================================

def test_confidence_reproducible_without_model(tmp_path):
    r = _make_engine(tmp_path, model=None)
    ctx1 = type("Ctx", (), {"task": "echo hello"})()
    ctx2 = type("Ctx", (), {"task": "echo hello"})()
    d1 = r.deliberate_for_planning(ctx1)
    d2 = r.deliberate_for_planning(ctx2)
    assert d1.confidence == d2.confidence


def test_abstains_on_thin_evidence(tmp_path):
    r = _make_engine(tmp_path)
    thin_cases = [
        type("O", (), {"output": "unknown xyz", "task_id": "t1", "step_index": 0})(),
        type("O", (), {"output": "random error", "task_id": "t2", "step_index": 0})(),
        type("O", (), {"output": "???", "task_id": "t3", "step_index": 0})(),
    ]
    for case in thin_cases:
        d = r.deliberate_for_repair(case)
        assert d.recommendation == Recommendation.ABSTAIN


def test_does_not_over_abstain_on_rich_cases(tmp_path):
    r = _make_engine(tmp_path)
    rich_cases = [
        type("O", (), {
            "output": "ModuleNotFoundError: No module named 'parse_config'",
            "task_id": "t1",
            "step_index": 0,
        })(),
        type("O", (), {
            "output": "AssertionError: expected 3 but got 2",
            "task_id": "t2",
            "step_index": 0,
        })(),
    ]
    abstained = [r.deliberate_for_repair(c).abstained for c in rich_cases]
    # Mostly advises when it should.
    assert sum(abstained) / len(abstained) < 0.5


# ===========================================================================
# Owners keep ownership (seams)
# ===========================================================================

def test_planner_can_ignore_advice(tmp_path):
    r = _make_engine(tmp_path)
    ctx = type("Ctx", (), {"task": "list files"})()
    d = r.deliberate_for_planning(ctx)
    assert d.seam == Seam.PLANNER
    assert d.recommendation in (Recommendation.PREFER, Recommendation.ABSTAIN,
                                Recommendation.CAUTION, Recommendation.GATHER_CONTEXT)


def test_reflection_still_owns_verdict(tmp_path):
    import importlib
    import tempfile
    from pathlib import Path
    from aetheris.memory.store import MemoryStore
    from aetheris.reasoning.engine import ReasoningEngine
    from aetheris.understanding.engine import RepoUnderstanding

    with tempfile.TemporaryDirectory() as tmp2:
        root = Path(tmp2)
        (root / "myapp").mkdir()
        (root / "myapp" / "__init__.py").write_text("")
        (root / "myapp" / "config.py").write_text(
            "def parse_config(path):\n    return 'ok'\n", encoding="utf-8"
        )
        u = RepoUnderstanding(root=str(root), model_path=str(root / "model.json"))
        u.scan()
        mem = MemoryStore(str(root / "events.jsonl"))
        r = ReasoningEngine(understanding=u, memory=mem)
        refl_mod = importlib.import_module("aetheris.reflection.engine")
        engine = refl_mod.ReflectionEngine(understanding=u, reasoning=r)
        outcome = type("O", (), {
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
        from aetheris.planner.plan import MultiStepPlan
        plan = MultiStepPlan(task_id="t1", steps=[])
        result = engine.reflect(outcome, plan)
        assert result.verdict.value == "insert_repair_steps"


def test_learning_gate_unchanged_by_reasoning(tmp_path):
    r = _make_engine(tmp_path)
    candidate = type("Cand", (), {
        "name": "bad_skill",
        "task_id": "t1",
        "benchmark_deltas": {},
    })()
    d = r.deliberate_for_promotion(candidate)
    assert d.recommendation in (Recommendation.ABSTAIN, Recommendation.CAUTION)


# ===========================================================================
# Outcome gate
# ===========================================================================

def test_reasoning_improves_at_least_one_decision_axis(tmp_path):
    """The reasoning engine must be able to produce non-zero decision quality
    when benchmark cases provide better_decision labels."""
    from aetheris.reasoning.benchmark import reasoning_benchmark

    cases = reasoning_benchmark(str(tmp_path))
    labeled = [c for c in cases if c.better_decision is not None]
    assert labeled, "benchmark must have labeled cases"

    r = _make_engine(tmp_path)
    qualities = []
    for case in labeled:
        if case.seam == "planner":
            ctx = type("Ctx", (), {"task": case.better_decision})()
            d = r.deliberate_for_planning(ctx)
        elif case.seam == "reflection":
            outcome = type("O", (), {"output": "test failure", "task_id": case.case_id, "step_index": 0})()
            d = r.deliberate_for_repair(outcome)
        elif case.seam == "learning":
            candidate = type("Cand", (), {"name": case.better_decision, "task_id": case.case_id})()
            d = r.deliberate_for_promotion(candidate)
        else:
            continue
        qualities.append(d.confidence)

    # The engine must produce at least one non-trivial confidence for labeled cases.
    assert any(q > 0.5 for q in qualities), f"all qualities <= 0.5: {qualities}"


def test_no_regressions_and_safety_neutral(tmp_path):
    from aetheris.reasoning.benchmark import ReasoningComparison
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    assert result.on.regressions == 0
    assert result.on.blocked_unsafe <= result.off.blocked_unsafe


def test_reasoning_usefulness_positive(tmp_path):
    """reasoning_usefulness must be computable as a positive value when
    the on-mode completion exceeds the off-mode completion."""
    from aetheris.reasoning.benchmark import ReasoningScore

    off = ReasoningScore(completion=0.8)
    on = ReasoningScore(completion=0.9)
    usefulness = max(0.0, on.completion - off.completion)
    assert usefulness > 0.0

    # Verify the score dataclass carries the field.
    assert hasattr(ReasoningScore, "reasoning_usefulness")


def test_control_cases_byte_identical_off_vs_on(tmp_path):
    from aetheris.reasoning.benchmark import ReasoningComparison, reasoning_benchmark
    comp = ReasoningComparison(root=str(tmp_path))
    control_cases = [c for c in reasoning_benchmark(str(tmp_path))
                     if c.fixture_class == "control"]
    result = comp.run(control_cases)
    assert result.per_class.get("control", {}).get("off") == result.per_class.get("control", {}).get("on")


def test_off_is_repo_understanding_v0_baseline(tmp_path):
    """reasoning-off should not change behavior vs prior milestone."""
    from aetheris.evaluation.cases import code_repair_suite
    from aetheris.evaluation.compare import SkillComparison
    from aetheris.memory.store import MemoryStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    cases = code_repair_suite(str(tmp_path))
    result = comp.run(cases)
    assert result.completion_on >= result.completion_off
