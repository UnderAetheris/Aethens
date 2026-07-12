"""Repo-Aware Coding Skills v0 — tests (milestone §8).

Exercises the data-only skill template, the read-only renderer, the three
deterministic fallbacks, valid gated rendering, reasoning advisory use +
abstention fallback, the repo-aware-vs-plain benchmark, and the promotion gate.
Includes the canary `test_reasoning_off_repo_aware_skill_equals_plain`.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from aetheris.planner.plan import MultiStepPlan
from aetheris.skills.repo_aware import (
    REPO_AWARE_TOOLS,
    FactRequest,
    RepoAwareSkill,
    RepoAwareSkillRenderer,
    _understanding_from_fixtures,
)
from aetheris.skills.repo_aware_benchmark import (
    RepoAwareComparison,
    reasoning_ci_gate_passes,
    skill_benchmark,
)
from aetheris.skills.repo_aware_seeds import (
    correct_module_fixture,
    helper_reuse_fixture,
    helper_reuse_skill,
    missing_import_skill,
    plain_twin,
    two_shape_skill,
)
from aetheris.skills.registry import SkillRegistry, SkillTemplate

EXISTING_GATED_TOOLS = set(REPO_AWARE_TOOLS)


def run_suite(path: str) -> types.SimpleNamespace:
    import os

    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.path.join(cwd, "src")},
    )
    return types.SimpleNamespace(all_passed=result.returncode == 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _edits(plan: MultiStepPlan) -> str:
    return " ".join(s.arg for s in plan.steps if s.tool == "edit_file")


def _shape_of(plan: MultiStepPlan) -> str:
    return plan.plan_source.split(":")[-1]


def _reuses_helper(plan: MultiStepPlan, name: str) -> bool:
    reuses = any(f"from helpers import {name}" in s.arg for s in plan.steps if s.tool == "edit_file")
    reimplements = any(f"def {name}" in s.arg for s in plan.steps)
    return reuses and not reimplements


def _reimplements(plan: MultiStepPlan) -> bool:
    return any("def " in s.arg and "import" not in s.arg for s in plan.steps)


def _engine_prefers(shape_id: str):
    class _FakeEngine:
        def deliberate_for_planning(self, ctx):
            return types.SimpleNamespace(recommended_approach=shape_id, abstained=False)

    return _FakeEngine()


def _engine_that_abstains():
    class _FakeEngine:
        def deliberate_for_planning(self, ctx):
            return types.SimpleNamespace(recommended_approach=None, abstained=True)

    return _FakeEngine()


# ---------------------------------------------------------------------------
# Fact binding
# ---------------------------------------------------------------------------


def test_skill_binds_correct_import_module_from_understanding():
    fx = correct_module_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(missing_import_skill(), fx.task)
    assert "from src.pkg.config import parse_config" in _edits(plan)


def test_missing_fact_falls_back_to_declared_default():
    fx = correct_module_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(
        missing_import_skill(), "fix missing import symbol=unknown_sym path=src/pkg/main.py"
    )
    assert "<best-effort module>" in _edits(plan)
    assert "unknown_sym" in _edits(plan)


def test_helper_reuse_shape_chosen_when_helper_exists():
    fx = helper_reuse_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(helper_reuse_skill(), fx.task)
    assert _reuses_helper(plan, "parse_config") and not _reimplements(plan)


# ---------------------------------------------------------------------------
# Reasoning advisory use + abstention fallback
# ---------------------------------------------------------------------------


def test_reasoning_chooses_between_candidate_shapes():
    fx = helper_reuse_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    # force reasoning to prefer the reuse shape regardless of facts
    skill = helper_reuse_skill()
    renderer = RepoAwareSkillRenderer(understanding=None, reasoning=_engine_prefers("reuse_helper"))
    plan = renderer.render(skill, fx.task)
    assert _shape_of(plan) == "reuse_helper"


def test_reasoning_abstention_falls_back_to_default_shape():
    skill = two_shape_skill()
    renderer = RepoAwareSkillRenderer(understanding=None, reasoning=_engine_that_abstains())
    plan = renderer.render(skill, "choose shape")
    assert _shape_of(plan) == "plain_shape"


def test_skill_holds_no_handle_or_tool():
    s = missing_import_skill()
    for banned in ("execute", "run", "edit", "query", "understanding", "reasoning", "tools"):
        assert not hasattr(s, banned)


# ---------------------------------------------------------------------------
# Valid rendering / no privilege / safety-gated
# ---------------------------------------------------------------------------


def test_render_produces_valid_dag_multistep_plan():
    fx = correct_module_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(missing_import_skill(), fx.task)
    assert plan.is_valid_dag()
    assert plan.plan_source.startswith("repo_aware_skill")


def test_rendered_steps_are_all_existing_gated_tools():
    fx = helper_reuse_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(helper_reuse_skill(), fx.task)
    assert all(step.tool in EXISTING_GATED_TOOLS for step in plan.steps)


def test_skill_plan_cannot_bypass_safety():
    fx = correct_module_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(missing_import_skill(), fx.task)
    # every step references an existing gated tool; no new execution path
    assert all(step.tool in EXISTING_GATED_TOOLS for step in plan.steps)


def test_reflection_repairs_failed_skill_step():
    from aetheris.reflection.engine import ReflectionEngine

    fx = correct_module_fixture()
    root = Path(tempfile.mkdtemp())
    u = _understanding_from_fixtures(root, fx.fixtures)
    plan = RepoAwareSkillRenderer(understanding=u).render(missing_import_skill(), fx.task)
    reflection = ReflectionEngine(understanding=u)
    outcome = types.SimpleNamespace(
        failure_kind="missing_import",
        output="ModuleNotFoundError: No module named 'parse_config'",
        step_index=0,
        task_id="t1",
        blocked=False,
    )
    verdict = reflection.reflect(outcome, plan)
    assert verdict.verdict == "insert_repair_steps"


# ---------------------------------------------------------------------------
# Measurable improvement over non-repo-aware twin
# ---------------------------------------------------------------------------


def test_repo_aware_beats_plain_twin_or_stays_unpromoted():
    for fx, skill in skill_benchmark():
        cmp = RepoAwareComparison().run(fx, skill)
        if cmp.promote:
            assert cmp.on.completion >= cmp.off.completion
            assert cmp.on.retries <= cmp.off.retries and cmp.on.repairs <= cmp.off.repairs
            assert cmp.on.regressions == 0 and cmp.on.blocked_unsafe <= cmp.off.blocked_unsafe
        else:
            assert not cmp.promote  # unpromoted is a valid, honest outcome


def test_promotion_is_reversible(tmp_path):
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    tpl = SkillTemplate(
        id="missing_import_repair", name="missing_import_repair",
        description="repo-aware", trigger_patterns=["missing import"],
        required_params=["symbol"], steps=(), version=1,
    )
    registered = reg.register(tpl)
    v = registered.version
    reg.retire(registered.id)
    retired = reg.get("missing_import_repair")
    assert retired is not None and retired.active is False
    assert "missing_import_repair" not in {s.id for s in reg.active_skills()}


# ---------------------------------------------------------------------------
# No regression / stability
# ---------------------------------------------------------------------------


def test_no_match_leaves_planner_unchanged():
    from aetheris.planner.planner import Planner

    assert missing_import_skill().match.extract_params("defrost the freezer") is None
    planner = Planner()
    plan = planner.plan_multi("defrost the freezer", "t1")
    # unchanged decomposed path — no skill source
    assert plan.plan_source == "decomposed"


def test_reasoning_off_repo_aware_skill_equals_plain():
    # With reasoning disabled, a repo-aware skill's behavior equals its plain
    # twin (the canary: if this fails, repo-awareness leaked into behavior).
    skill = two_shape_skill()
    r_off = RepoAwareSkillRenderer(understanding=None, reasoning=None)
    plan_repo = r_off.render(skill, "choose shape")
    plan_plain = r_off.render(plain_twin(skill), "choose shape")
    assert [(s.tool, s.arg) for s in plan_repo.steps] == [(s.tool, s.arg) for s in plan_plain.steps]
    assert _shape_of(plan_repo) == _shape_of(plan_plain)


def test_control_and_hardening_suites_green():
    from pathlib import Path

    suite = Path(__file__).parent / "test_reasoning_hardening.py"
    assert run_suite(str(suite)).all_passed
    assert reasoning_ci_gate_passes()  # prior guard intact
