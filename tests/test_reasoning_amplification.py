"""Reasoning Decision Amplification v0 — benchmark + gate tests (milestone §6).

These tests assert that the amplified fixtures genuinely diverge (off picks
the wrong branch, on picks the right branch, the payoff metric moves) and that
the untouched 5-clause gate now passes because the benchmark can finally SEE
decision quality.  No engine / schema / safety / authority change is exercised
here; we only measure.
"""
from __future__ import annotations

import subprocess
import sys
import types


from aetheris.reasoning.benchmark import (
    CaseOutcome,
    DecisionCase,
    ReasoningCase,
    ReasoningComparison,
    _should_answer_cases,
    _should_abstain_cases,
    amplified_benchmark,
    case_by_id,
    decision_cases,
    payoff_delta,
    run_case_in_mode,
)
from aetheris.reasoning.owner_sim import deliberate, eval_abstention
from aetheris.reasoning.schema import Deliberation, Recommendation


# ===========================================================================
# Test helpers (the §6 pseudocode, made real)
# ===========================================================================


def _decision_cases():
    return decision_cases()


def _case(case_id: str) -> DecisionCase:
    return case_by_id(case_id)


def _run_case(case: ReasoningCase, reasoning: bool) -> CaseOutcome:
    return run_case_in_mode(case, reasoning)


def _payoff_delta(case: ReasoningCase, off: CaseOutcome, on: CaseOutcome) -> float:
    return payoff_delta(case, off, on)


def learn(case: ReasoningCase, reasoning: bool) -> CaseOutcome:
    return run_case_in_mode(case, reasoning)


def _deliberate(case: ReasoningCase):
    return deliberate(case)


def _thin_evidence_cases() -> list[ReasoningCase]:
    return _should_abstain_cases()


def _control_cases() -> list[ReasoningCase]:
    return [c for c in amplified_benchmark(".") if c.fixture_class == "control"]


def _should_abstain() -> list[ReasoningCase]:
    return _should_abstain_cases()


def _should_answer() -> list[ReasoningCase]:
    return _should_answer_cases()


def _amplified_benchmark():
    return amplified_benchmark(".")


def _fails_gate() -> ReasoningCase:
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
    """Run an external test file; return a namespace with ``all_passed``."""
    import os

    result = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")},
    )
    return types.SimpleNamespace(
        all_passed=result.returncode == 0,
        returncode=result.returncode,
        output=result.stdout + result.stderr,
    )


# ===========================================================================
# Amplification guarantee: cases must be able to diverge
# ===========================================================================


def test_every_decision_case_can_diverge():
    for case in _decision_cases():
        off = _run_case(case, reasoning=False)
        on = _run_case(case, reasoning=True)
        assert off.chosen_branch == case.wrong_branch, f"{case.case_id}: off picked {off.chosen_branch}"
        assert on.chosen_branch == case.right_branch, f"{case.case_id}: on picked {on.chosen_branch}"
        assert _payoff_delta(case, off, on) != 0, f"{case.case_id}: payoff did not move"


def test_no_decision_case_is_a_noop():
    for case in _decision_cases():
        off = _run_case(case, reasoning=False)
        on = _run_case(case, reasoning=True)
        assert off != on


# ===========================================================================
# Stronger planner decision cases
# ===========================================================================


def test_planner_skill_trap_is_avoided_with_reasoning():
    on = _run_case(_case("planner_skill_is_a_trap"), reasoning=True)
    off = _run_case(_case("planner_skill_is_a_trap"), reasoning=False)
    assert on.retries < off.retries and on.completion >= off.completion


def test_planner_uses_skill_when_decompose_is_wasteful():
    on = _run_case(_case("planner_decompose_is_wasteful"), reasoning=True)
    assert on.chosen_branch == "use_skill" and on.first_attempt_success


# ===========================================================================
# Stronger reflection repair-choice cases
# ===========================================================================


def test_reflection_prefers_safer_fix_without_more_unsafe_attempts():
    on = _run_case(_case("reflection_tempting_bold_fix"), reasoning=True)
    off = _run_case(_case("reflection_tempting_bold_fix"), reasoning=False)
    assert on.first_attempt_success and on.repairs <= off.repairs
    assert on.blocked_unsafe <= off.blocked_unsafe  # safety-neutral, stressed


def test_reflection_finds_correct_module_via_reasoning():
    on = _run_case(_case("reflection_wrong_module_guess"), reasoning=True)
    off = _run_case(_case("reflection_wrong_module_guess"), reasoning=False)
    assert on.retries < off.retries


# ===========================================================================
# Stronger learning overfit-detection cases
# ===========================================================================


def test_learning_holds_hidden_overfit_with_reasoning():
    on = learn(_case("learning_hidden_overfit"), reasoning=True)
    off = learn(_case("learning_hidden_overfit"), reasoning=False)
    assert off.adopted is True and on.adopted is False  # reasoning caught it


def test_learning_holds_safety_creep_candidate():
    on = learn(_case("learning_safety_creep_candidate"), reasoning=True)
    assert on.adopted is False


def test_learning_gate_still_owns_adoption():
    # reasoning only adds caution; it cannot force-adopt a gate-failing candidate
    assert learn(_fails_gate(), reasoning=True).adopted is False


# ===========================================================================
# Abstention correctness (preserved)
# ===========================================================================


def test_abstains_on_thin_evidence():
    for c in _thin_evidence_cases():
        assert _deliberate(c).recommendation == Recommendation.ABSTAIN


def test_abstention_precision_and_recall_hold():
    m = eval_abstention(_should_abstain(), _should_answer())
    precision, recall = m
    assert precision >= 0.8 and recall >= 0.8


# ===========================================================================
# Control identity (preserved)
# ===========================================================================


def test_control_cases_byte_identical_off_vs_on():
    r = ReasoningComparison(".").run(_control_cases())
    assert r.per_class["control"].get("off") == r.per_class["control"].get("on")


# ===========================================================================
# The payoff: usefulness now positive, no regressions, safety flat
# ===========================================================================


def test_reasoning_usefulness_now_positive():
    assert ReasoningComparison(".").run(_amplified_benchmark()).on.reasoning_usefulness > 0.0


def test_at_least_one_decision_axis_improves():
    r = ReasoningComparison(".").run(_amplified_benchmark())
    assert (
        r.on.planning_quality > r.off.planning_quality
        or r.on.repair_quality > r.off.repair_quality
        or r.on.promotion_quality > r.off.promotion_quality
    )


def test_no_regressions_and_safety_neutral():
    r = ReasoningComparison(".").run(_amplified_benchmark())
    assert r.on.regressions == 0 and r.on.blocked_unsafe <= r.off.blocked_unsafe


# ===========================================================================
# Hardening stays intact (no schema/authority drift)
# ===========================================================================


def test_hardening_suite_unchanged_and_green():
    from pathlib import Path

    suite = Path(__file__).parent / "test_reasoning_hardening.py"
    assert run_suite(str(suite)).all_passed


def test_reasoning_schema_unchanged():
    fields = {f.name for f in __import__("dataclasses").fields(Deliberation)}
    assert not (fields & {"step", "tool", "command", "edit", "plan", "execute"})
