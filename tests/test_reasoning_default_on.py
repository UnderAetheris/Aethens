"""Deliberative Reasoning Default-On Hardening v1 — tests (milestone §4).

These re-assert the structural guarantees against the configuration users
actually run (reasoning ON by default), prove the opt-out is a true rollback,
and confirm the CI gate still passes.  No engine / schema / safety / authority
change is exercised here; we only verify the flip + enforcement.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
import types

import pytest

from aetheris.api.state import AppState
from aetheris.config import Config, resolve_reasoning_enabled
from aetheris.reasoning.benchmark import (
    DecisionCase,
    ReasoningComparison,
    _should_abstain_cases,
    amplified_benchmark,
    case_by_id,
    run_case_in_mode,
)
from aetheris.reasoning.owner_sim import deliberate
from aetheris.reasoning.schema import Deliberation, Recommendation


# ===========================================================================
# Helpers
# ===========================================================================


def _fails_gate() -> DecisionCase:
    """A candidate whose measured adoption gate fails (no headline gain)."""
    return DecisionCase(
        case_id="learning_gate_failing",
        seam="learning",
        fixture_class="overfit_adoption",
        better_decision="hold",
        wrong_branch="adopt",
        right_branch="hold",
        payoff_metric="false_adopt",
        divergence_required=True,
        setup={"headline_completion_delta": 0.0},
    )


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


# ===========================================================================
# Default-on wiring
# ===========================================================================


def test_default_config_enables_reasoning(tmp_path):
    assert Config().reasoning_enabled is True
    app = AppState.create(root=str(tmp_path / "data"), config=Config(), env={})
    assert app.reasoning is not None


def test_env_optout_forces_off_and_is_true_rollback(tmp_path):
    app = AppState.create(
        root=str(tmp_path / "data"), config=Config(), env={"AETHERIS_REASONING": "off"}
    )
    assert app.reasoning is None
    # The off-path still produces the byte-identical Repo Understanding v0
    # baseline: control cases are identical off vs on.
    from aetheris.reasoning.benchmark import reasoning_benchmark

    control = [c for c in reasoning_benchmark(".") if c.fixture_class == "control"]
    res = ReasoningComparison(str(tmp_path / "data")).run(control)
    assert res.per_class["control"]["off"] == res.per_class["control"]["on"]


def test_malformed_env_defers_to_config_never_forces_on(tmp_path):
    on = AppState.create(
        root=str(tmp_path / "on"), config=Config(reasoning_enabled=True),
        env={"AETHERIS_REASONING": "maybe"},
    )
    off = AppState.create(
        root=str(tmp_path / "off"), config=Config(reasoning_enabled=False),
        env={"AETHERIS_REASONING": "maybe"},
    )
    assert on.reasoning is not None
    assert off.reasoning is None


def test_resolve_precedence_is_explicit(tmp_path):
    cfg = Config(reasoning_enabled=True)
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "off"}) is False
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "0"}) is False
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "false"}) is False
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "on"}) is True
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "1"}) is True
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "true"}) is True
    # unset / malformed -> config default, never silently forced on
    assert resolve_reasoning_enabled(cfg, {}) is True
    assert resolve_reasoning_enabled(cfg, {"AETHERIS_REASONING": "garbage"}) is True


# ===========================================================================
# Guarantees re-asserted on the default-on (live) path
# ===========================================================================


def test_schema_still_cannot_express_an_action_default_on():
    fields = {f.name for f in dataclasses.fields(Deliberation)}
    assert not (fields & {"step", "tool", "command", "edit", "shell",
                          "path_to_write", "plan", "apply", "execute"})


def test_engine_has_no_authority_on_default_path(tmp_path):
    r = AppState.create(
        root=str(tmp_path / "data"), config=Config(), env={}
    ).reasoning
    for banned in ("execute", "apply", "edit", "run", "shell",
                   "write_file", "mutate_plan", "set_verdict", "safety", "tools"):
        assert not hasattr(r, banned)


def test_deliberation_immutable_default_on():
    d = Deliberation(seam=__import__("aetheris.reasoning.schema", fromlist=["Seam"]).Seam.PLANNER,
                     subject="x", confidence=0.8)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(d, "confidence", 0.99)


def test_abstention_still_first_class_default_on():
    for c in _should_abstain_cases():
        assert deliberate(c).recommendation == Recommendation.ABSTAIN


def test_owners_keep_ownership_default_on():
    # Learning gate unchanged: a gate-failing candidate is still rejected.
    assert run_case_in_mode(_fails_gate(), True).adopted is False
    # Planner still owns the plan; on the default path it picks the right
    # (divergent) branch when reasoning is available.
    planner = case_by_id("planner_skill_is_a_trap")
    assert run_case_in_mode(planner, True).chosen_branch == "decompose"
    reflection = case_by_id("reflection_wrong_module_guess")
    assert run_case_in_mode(reflection, True).chosen_branch == "correct_module"


def test_safety_neutral_on_default_configuration():
    res = ReasoningComparison(".").run(amplified_benchmark("."))
    assert res.on.blocked_unsafe <= res.off.blocked_unsafe


def test_ci_gate_still_passes():
    assert ReasoningComparison(".").run(amplified_benchmark(".")).gate.adopt_default_on is True


def test_hardening_suite_unchanged_and_green():
    from pathlib import Path

    suite = Path(__file__).parent / "test_reasoning_hardening.py"
    assert run_suite(str(suite)).all_passed
