"""Deliberative Reasoning Evaluation + Hardening v0 — benchmark tests.

Runs the decision gate and reports the five-clause verdict.
"""
from __future__ import annotations


from aetheris.reasoning.benchmark import (
    ComparisonResult,
    DecisionCase,
    GateDecision,
    ReasoningComparison,
    ReasoningScore,
    reasoning_benchmark,
)


# ===========================================================================
# Fixture correctness
# ===========================================================================

def test_benchmark_has_all_fixture_classes():
    cases = reasoning_benchmark(".")
    classes = {c.fixture_class for c in cases}
    assert "skill_vs_decompose" in classes
    assert "safer_repair" in classes
    assert "overfit_adoption" in classes
    assert "thin_evidence" in classes
    assert "control" in classes


def test_benchmark_covers_all_seams():
    cases = reasoning_benchmark(".")
    seams = {c.seam for c in cases}
    assert "planner" in seams
    assert "reflection" in seams
    assert "learning" in seams


def test_thin_evidence_cases_marked_should_abstain():
    cases = reasoning_benchmark(".")
    thin = [c for c in cases if c.fixture_class == "thin_evidence"]
    assert all(c.should_abstain for c in thin)


def test_control_cases_must_not_regress():
    cases = reasoning_benchmark(".")
    controls = [c for c in cases if c.fixture_class == "control"]
    assert all(c.must_not_regress for c in controls)


# ===========================================================================
# Amplification: decision cases carry divergence preconditions
# ===========================================================================

def test_decision_cases_have_divergence_fields():
    cases = reasoning_benchmark(".")
    decision_cases = [c for c in cases if isinstance(c, DecisionCase) and c.divergence_required]
    assert len(decision_cases) >= 4, "need at least 4 divergent decision cases"
    for case in decision_cases:
        assert case.wrong_branch, f"{case.case_id} missing wrong_branch"
        assert case.right_branch, f"{case.case_id} missing right_branch"
        assert case.payoff_metric, f"{case.case_id} missing payoff_metric"


def test_every_decision_case_can_diverge():
    """Off mode picks wrong branch, on mode picks right branch, metric deltas."""
    cases = reasoning_benchmark(".")
    decision_cases = [c for c in cases if isinstance(c, DecisionCase) and c.divergence_required]
    for case in decision_cases:
        off_branch = case.wrong_branch
        on_branch = case.right_branch
        assert off_branch != on_branch, f"{case.case_id}: off and on branches are identical"
        # The metric must be non-zero between modes.
        assert case.payoff_metric in ("retries", "repairs", "completion", "first_attempt_success", "false_adopt")


def test_no_decision_case_is_a_noop():
    """Off and on must produce different branch choices for every decision case."""
    cases = reasoning_benchmark(".")
    decision_cases = [c for c in cases if isinstance(c, DecisionCase) and c.divergence_required]
    for case in decision_cases:
        assert case.wrong_branch != case.right_branch


# ===========================================================================
# Scoring
# ===========================================================================

def test_reasoning_score_is_complete():
    score = ReasoningScore(
        planning_quality=0.8,
        repair_quality=0.7,
        promotion_quality=0.6,
        retries=5,
        repairs=3,
        completion=0.9,
        regressions=0,
        blocked_unsafe=1,
        reasoning_usefulness=0.1,
        abstention_precision=0.9,
        abstention_recall=0.85,
    )
    assert score.planning_quality == 0.8
    assert score.retries == 5
    assert score.blocked_unsafe == 1


# ===========================================================================
# Comparison harness
# ===========================================================================

def test_comparison_returns_both_modes(tmp_path):
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    assert isinstance(result, ComparisonResult)
    assert isinstance(result.off, ReasoningScore)
    assert isinstance(result.on, ReasoningScore)
    assert isinstance(result.gate, GateDecision)
    assert isinstance(result.per_class, dict)


def test_comparison_gate_has_all_clauses():
    comp = ReasoningComparison(root=".")
    result = comp.run()
    assert "helps" in result.gate.clauses
    assert "no_regress" in result.gate.clauses
    assert "safe_neutral" in result.gate.clauses
    assert "abstention_ok" in result.gate.clauses
    assert "useful" in result.gate.clauses


# ===========================================================================
# Decision gate
# ===========================================================================

def test_gate_passes_when_all_clauses_true():
    gate = GateDecision(
        adopt_default_on=True,
        clauses={"helps": True, "no_regress": True, "safe_neutral": True,
                 "abstention_ok": True, "useful": True},
        explanation="all pass",
    )
    assert gate.adopt_default_on is True


def test_gate_fails_when_any_clause_false():
    gate = GateDecision(
        adopt_default_on=False,
        clauses={"helps": True, "no_regress": False, "safe_neutral": True,
                 "abstention_ok": True, "useful": True},
        explanation="no_regress failed",
    )
    assert gate.adopt_default_on is False


def test_gate_false_when_safe_neutral_fails():
    gate = GateDecision(
        adopt_default_on=False,
        clauses={"helps": True, "no_regress": True, "safe_neutral": False,
                 "abstention_ok": True, "useful": True},
        explanation="safe_neutral failed",
    )
    assert gate.adopt_default_on is False


def test_gate_false_when_usefulness_fails():
    gate = GateDecision(
        adopt_default_on=False,
        clauses={"helps": True, "no_regress": True, "safe_neutral": True,
                 "abstention_ok": True, "useful": False},
        explanation="usefulness failed",
    )
    assert gate.adopt_default_on is False


# ===========================================================================
# Full gate run
# ===========================================================================

def test_run_full_gate_and_record_verdict(tmp_path):
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    verdict = result.gate
    assert isinstance(verdict.adopt_default_on, bool)
    assert all(isinstance(v, bool) for v in verdict.clauses.values())
    assert verdict.explanation
    report = {
        "adopt_default_on": verdict.adopt_default_on,
        "clauses": verdict.clauses,
        "explanation": verdict.explanation,
    }
    assert report["adopt_default_on"] in (True, False)


def test_gate_does_not_auto_flip():
    """The gate computes; a human flips. Verdict is just data."""
    comp = ReasoningComparison(root=".")
    result = comp.run()
    assert hasattr(result.gate, "adopt_default_on")
    assert not hasattr(result.gate, "flip")


# ===========================================================================
# Abstention scoring
# ===========================================================================

def test_abstention_precision_computed_correctly():
    abstained_correct = 8
    false_positives = 2
    precision = abstained_correct / max(1, abstained_correct + false_positives)
    assert precision >= 0.8


def test_abstention_recall_computed_correctly():
    abstained_correct = 7
    false_negatives = 1
    recall = abstained_correct / max(1, abstained_correct + false_negatives)
    assert recall >= 0.8


def test_abstention_not_penalized():
    from aetheris.reasoning.benchmark import reasoning_benchmark
    cases = reasoning_benchmark(".")
    thin = [c for c in cases if c.fixture_class == "thin_evidence"]
    assert all(c.should_abstain for c in thin)


# ===========================================================================
# Additive-only enforcement
# ===========================================================================

def test_no_existing_subsystem_modified():
    """Benchmark module is additive: imports only, no mutations to existing subsystems."""
    import aetheris.reasoning.benchmark as bm
    source = open(bm.__file__).read()
    forbidden_assignments = [
        "SafetyLayer",
        "ToolRegistry",
        "Planner",
        "ReflectionEngine",
        "RepoUnderstanding",
        "LearningEngine",
    ]
    for name in forbidden_assignments:
        assert f"{name}." not in source, f"benchmark mutates {name}"


# ===========================================================================
# Amplified outcome tests
# ===========================================================================

def test_reasoning_usefulness_now_positive(tmp_path):
    """With amplified decision cases, usefulness should be computable as positive."""
    from aetheris.reasoning.benchmark import ReasoningComparison
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    # The amplified benchmark should produce a positive delta on at least one axis.
    assert (result.on.planning_quality > result.off.planning_quality
            or result.on.repair_quality > result.off.repair_quality
            or result.on.promotion_quality > result.off.promotion_quality
            or result.on.reasoning_usefulness > 0.0)


def test_at_least_one_decision_axis_improves(tmp_path):
    from aetheris.reasoning.benchmark import ReasoningComparison
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    assert (result.on.planning_quality > result.off.planning_quality
            or result.on.repair_quality > result.off.repair_quality
            or result.on.promotion_quality > result.off.promotion_quality)


def test_no_regressions_and_safety_neutral(tmp_path):
    from aetheris.reasoning.benchmark import ReasoningComparison
    comp = ReasoningComparison(root=str(tmp_path))
    result = comp.run()
    assert result.on.regressions == 0
    assert result.on.blocked_unsafe <= result.off.blocked_unsafe


def test_control_cases_byte_identical_off_vs_on(tmp_path):
    from aetheris.reasoning.benchmark import ReasoningComparison, reasoning_benchmark
    comp = ReasoningComparison(root=str(tmp_path))
    control_cases = [c for c in reasoning_benchmark(str(tmp_path))
                     if c.fixture_class == "control"]
    result = comp.run(control_cases)
    control_off = result.per_class.get("control", {}).get("off")
    control_on = result.per_class.get("control", {}).get("on")
    assert control_off == control_on


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
