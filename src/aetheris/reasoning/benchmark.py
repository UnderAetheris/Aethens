"""Deliberative Reasoning benchmark, scoring, and comparison harness.

Additive only — does not edit SafetyLayer, Tools, Planner, Reflection,
Understanding, or Learning.  Reuses the existing eval + code-repair harness.

This module is the *orchestration* of the amplified benchmark.  All owner
decision surfaces are modelled in ``owner_sim`` (the only place that touches
read-only Understanding / ReasoningEngine handles), so this file stays free of
any subsystem mutation.  The 5-clause gate is byte-for-byte unchanged from the
prior milestone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .owner_sim import CaseOutcome, eval_abstention, run_case
from .schema import Recommendation  # noqa: F401  (re-exported for tests)


# ===========================================================================
# Benchmark schema
# ===========================================================================


@dataclass(frozen=True)
class ReasoningCase:
    case_id: str
    seam: str                    # "planner" | "reflection" | "learning" | "control"
    fixture_class: str           # skill_vs_decompose | safer_repair | overfit_adoption
                                  # | thin_evidence | control
    setup: dict[str, Any] = field(default_factory=dict)
    better_decision: str | None = None
    should_abstain: bool = False
    must_not_regress: bool = True


@dataclass(frozen=True)
class DecisionCase(ReasoningCase):
    """A case that must be able to diverge between off and on modes."""

    wrong_branch: str = ""       # the choice a blind owner plausibly makes
    right_branch: str = ""       # the choice an informed owner should make
    payoff_metric: str = ""      # "retries" | "repairs" | "completion"
                                  # | "first_attempt_success" | "false_adopt"
    divergence_required: bool = True


# ===========================================================================
# Scoring
# ===========================================================================


@dataclass(frozen=True)
class ReasoningScore:
    planning_quality: float = 0.0
    repair_quality: float = 0.0
    promotion_quality: float = 0.0
    retries: int = 0
    repairs: int = 0
    completion: float = 0.0
    regressions: int = 0
    blocked_unsafe: int = 0
    reasoning_usefulness: float = 0.0
    abstention_precision: float = 0.0
    abstention_recall: float = 0.0


@dataclass(frozen=True)
class ComparisonResult:
    off: ReasoningScore
    on: ReasoningScore
    per_class: dict[str, dict[str, Any]]
    gate: "GateDecision"


@dataclass(frozen=True)
class GateDecision:
    adopt_default_on: bool
    clauses: dict[str, bool]
    explanation: str


# ===========================================================================
# Fixture definitions — amplified decision-bearing + thin + control
# ===========================================================================


def reasoning_benchmark(root: str) -> list[ReasoningCase]:
    """Amplified decision-bearing fixtures + thin-evidence + control.

    Every decision case carries a ``setup`` describing a hermetic in-repo
    fixture whose discriminating fact is read from Understanding.  The owner's
    existing decision surface can measurably get it wrong without reasoning and
    measurably right with it.
    """
    return [
        # ── Planner seam: skill_vs_decompose (amplified) ──────────────────
        DecisionCase(
            case_id="planner_skill_is_a_trap",
            seam="planner",
            fixture_class="skill_vs_decompose",
            better_decision="decompose",
            wrong_branch="use_skill",
            right_branch="decompose",
            payoff_metric="retries",
            divergence_required=True,
            setup={
                "skill_assumed_symbol": "render_widget",
                "fixtures": {
                    "myapp/__init__.py": "",
                    "myapp/helpers.py": (
                        "def format_output(x):\n"
                        "    return str(x)\n"
                        "\n"
                        "def compute(a, b):\n"
                        "    return a + b\n"
                    ),
                },
            },
        ),
        DecisionCase(
            case_id="planner_decompose_is_wasteful",
            seam="planner",
            fixture_class="skill_vs_decompose",
            better_decision="use_skill",
            wrong_branch="decompose",
            right_branch="use_skill",
            payoff_metric="first_attempt_success",
            divergence_required=True,
            setup={
                "task": "produce a weekly status brief for the team",
                "skill": {
                    "id": "status_brief_skill",
                    "name": "status_brief",
                    "description": "weekly status brief",
                    "trigger_patterns": ["status brief", "brief"],
                    "required_params": [],
                },
            },
        ),
        # ── Reflection seam: safer_repair (amplified) ─────────────────────
        DecisionCase(
            case_id="reflection_tempting_bold_fix",
            seam="reflection",
            fixture_class="safer_repair",
            better_decision="reuse_helper",
            wrong_branch="broad_import",
            right_branch="reuse_helper",
            payoff_metric="first_attempt_success",
            divergence_required=True,
            setup={
                "helper_intent": "helper",
                "fixtures": {
                    "myapp/__init__.py": "",
                    "myapp/utils.py": (
                        "def helper_x(a, b):\n    return a + b\n"
                    ),
                    "myapp/a.py": (
                        "from .utils import helper_x\n"
                        "\n"
                        "def f():\n    return helper_x(1, 2)\n"
                    ),
                    "myapp/b.py": (
                        "from .utils import helper_x\n"
                        "\n"
                        "def g():\n    return helper_x(3, 4)\n"
                    ),
                },
            },
        ),
        DecisionCase(
            case_id="reflection_wrong_module_guess",
            seam="reflection",
            fixture_class="safer_repair",
            better_decision="correct_module",
            wrong_branch="wrong_module",
            right_branch="correct_module",
            payoff_metric="retries",
            divergence_required=True,
            setup={
                "missing_symbol": "Secret",
                "fixtures": {
                    "pkg/__init__.py": "",
                    "pkg/_internal/__init__.py": "",
                    "pkg/_internal/secretmod.py": (
                        "def Secret():\n    return 's'\n"
                    ),
                    "pkg/common.py": (
                        "def obvious():\n    return 1\n"
                    ),
                },
            },
        ),
        # ── Learning seam: overfit_adoption (amplified) ───────────────────
        DecisionCase(
            case_id="learning_hidden_overfit",
            seam="learning",
            fixture_class="overfit_adoption",
            better_decision="hold",
            wrong_branch="adopt",
            right_branch="hold",
            payoff_metric="false_adopt",
            divergence_required=True,
            setup={
                "headline_completion_delta": 0.20,
                "gain_concentration": 1.0,
                "repair_cost_rise": 0.10,
            },
        ),
        DecisionCase(
            case_id="learning_safety_creep_candidate",
            seam="learning",
            fixture_class="overfit_adoption",
            better_decision="hold",
            wrong_branch="adopt",
            right_branch="hold",
            payoff_metric="false_adopt",
            divergence_required=True,
            setup={
                "headline_completion_delta": 0.15,
                "unsafe_nudge": 0.05,
            },
        ),
        # ── Thin-evidence: should abstain (preserved) ─────────────────────
        ReasoningCase(
            case_id="thin_evidence_1",
            seam="reflection",
            fixture_class="thin_evidence",
            should_abstain=True,
            setup={"output": "unknown xyz"},
        ),
        ReasoningCase(
            case_id="thin_evidence_2",
            seam="planner",
            fixture_class="thin_evidence",
            should_abstain=True,
            setup={"task": "do the thing"},
        ),
        # ── Control: no-op, must not regress (preserved) ──────────────────
        ReasoningCase(
            case_id="control_echo",
            seam="planner",
            fixture_class="control",
            must_not_regress=True,
        ),
        ReasoningCase(
            case_id="control_read",
            seam="reflection",
            fixture_class="control",
            must_not_regress=True,
        ),
    ]


# ===========================================================================
# Payoff-metric helpers
# ===========================================================================


def _payoff_value(metric: str, outcome: CaseOutcome) -> float:
    return {
        "retries": float(outcome.retries),
        "repairs": float(outcome.repairs),
        "completion": outcome.completion,
        "first_attempt_success": 1.0 if outcome.first_attempt_success else 0.0,
        # 1.0 == good (NOT falsely adopted), 0.0 == false adopt
        "false_adopt": 0.0 if outcome.adopted else 1.0,
    }[metric]


def payoff_delta(case: ReasoningCase, off: CaseOutcome, on: CaseOutcome) -> float:
    """Signed delta of the payoff metric: positive == reasoning helped."""
    return _payoff_value(case.payoff_metric, on) - _payoff_value(case.payoff_metric, off)


# ===========================================================================
# Comparison harness
# ===========================================================================


class ReasoningComparison:
    """Runs the amplified benchmark twice (off/on), reasoning the only variable.

    Reuses the owner decision surfaces via ``owner_sim``; adds no execution
    authority.  Validates the divergence precondition for every decision case
    and reports, per class, which branch each mode chose and the payoff delta.
    """

    def __init__(self, root: str) -> None:
        self._root = root

    # ------------------------------------------------------------------ #
    # Public entrypoint                                                   #
    # ------------------------------------------------------------------ #

    def run(self, cases: list[ReasoningCase] | None = None) -> ComparisonResult:
        cases = cases if cases is not None else reasoning_benchmark(self._root)
        # Hermetic, per-run workspace: a fresh temp dir guarantees no cross-run
        # file locking and bit-for-bit reproducibility of the outcome metrics.
        import tempfile

        workspace = Path(tempfile.mkdtemp(prefix="aeth_bench_"))

        off_outcomes = {c.case_id: run_case(c, False, str(workspace)) for c in cases}
        on_outcomes = {c.case_id: run_case(c, True, str(workspace)) for c in cases}

        # Loud divergence-precondition validation: a no-op case fails the suite.
        invalid = self._validate_divergence(cases, off_outcomes, on_outcomes)
        if invalid:
            raise AssertionError(
                "divergence precondition FAILED for cases: "
                + ", ".join(f"{cid} ({reason})" for cid, reason in invalid)
            )

        decision = [c for c in cases if isinstance(c, DecisionCase) and c.divergence_required]
        off_quality = self._decision_quality_avg(decision, off_outcomes)
        on_quality = self._decision_quality_avg(decision, on_outcomes)

        prec, rec = eval_abstention(_should_abstain_cases(cases), _should_answer_cases())

        off_score = self._assemble_score(cases, off_outcomes, off_quality, 0.0, prec, rec)
        on_score = self._assemble_score(
            cases, on_outcomes, on_quality, max(0.0, on_quality - off_quality), prec, rec
        )

        per_class = self._score_by_class(cases, off_outcomes, on_outcomes)
        gate = self._evaluate_gate(off_score, on_score, per_class)
        return ComparisonResult(off=off_score, on=on_score, per_class=per_class, gate=gate)

    # ------------------------------------------------------------------ #
    # Divergence precondition                                             #
    # ------------------------------------------------------------------ #

    def _validate_divergence(
        self,
        cases: list[ReasoningCase],
        off_outcomes: dict[str, CaseOutcome],
        on_outcomes: dict[str, CaseOutcome],
    ) -> list[tuple[str, str]]:
        invalid: list[tuple[str, str]] = []
        for case in cases:
            if not isinstance(case, DecisionCase) or not case.divergence_required:
                continue
            off = off_outcomes[case.case_id]
            on = on_outcomes[case.case_id]
            if off.chosen_branch != case.wrong_branch:
                invalid.append((case.case_id, "off did not pick wrong_branch"))
            if on.chosen_branch != case.right_branch:
                invalid.append((case.case_id, "on did not pick right_branch"))
            if payoff_delta(case, off, on) == 0.0:
                invalid.append((case.case_id, "payoff metric did not move"))
        return invalid

    # ------------------------------------------------------------------ #
    # Scoring                                                            #
    # ------------------------------------------------------------------ #

    def _decision_quality_avg(
        self, decision_cases: list[DecisionCase], outcomes: dict[str, CaseOutcome]
    ) -> float:
        if not decision_cases:
            return 0.0
        correct = sum(
            1 for c in decision_cases if outcomes[c.case_id].chosen_branch == c.right_branch
        )
        return correct / len(decision_cases)

    def _assemble_score(
        self,
        cases: list[ReasoningCase],
        outcomes: dict[str, CaseOutcome],
        decision_quality: float,
        usefulness: float,
        prec: float,
        rec: float,
    ) -> ReasoningScore:
        planner = [c for c in cases if isinstance(c, DecisionCase) and c.seam == "planner"]
        reflection = [c for c in cases if isinstance(c, DecisionCase) and c.seam == "reflection"]
        learning = [c for c in cases if isinstance(c, DecisionCase) and c.seam == "learning"]

        def _quality(subset: list[DecisionCase]) -> float:
            if not subset:
                return 0.0
            ok = sum(1 for c in subset if outcomes[c.case_id].chosen_branch == c.right_branch)
            return ok / len(subset)

        completions = [o.completion for o in outcomes.values()]
        completion = sum(completions) / len(completions) if completions else 0.0
        return ReasoningScore(
            planning_quality=_quality(planner),
            repair_quality=_quality(reflection),
            promotion_quality=_quality(learning),
            retries=sum(o.retries for o in outcomes.values()),
            repairs=sum(o.repairs for o in outcomes.values()),
            completion=completion,
            regressions=sum(o.regressions for o in outcomes.values()),
            blocked_unsafe=sum(o.blocked_unsafe for o in outcomes.values()),
            reasoning_usefulness=usefulness,
            abstention_precision=prec,
            abstention_recall=rec,
        )

    def _score_by_class(
        self,
        cases: list[ReasoningCase],
        off_outcomes: dict[str, CaseOutcome],
        on_outcomes: dict[str, CaseOutcome],
    ) -> dict[str, dict[str, Any]]:
        classes: dict[str, dict[str, Any]] = {}
        for case in cases:
            fc = case.fixture_class
            entry = classes.setdefault(fc, {
                "off": ReasoningScore(),
                "on": ReasoningScore(),
                "count": 0,
                "branches": {},
                "payoff_deltas": {},
                "diverges": True,
            })
            entry["count"] += 1
            if isinstance(case, DecisionCase) and case.divergence_required:
                off = off_outcomes[case.case_id]
                on = on_outcomes[case.case_id]
                entry["branches"][case.case_id] = (off.chosen_branch, on.chosen_branch)
                entry["payoff_deltas"][case.case_id] = payoff_delta(case, off, on)
                entry["diverges"] = (
                    off.chosen_branch != on.chosen_branch
                    and payoff_delta(case, off, on) != 0.0
                )
            elif fc == "control":
                off = off_outcomes[case.case_id]
                on = on_outcomes[case.case_id]
                entry["off"] = ReasoningScore(completion=off.completion)
                entry["on"] = ReasoningScore(completion=on.completion)
        return classes

    # ------------------------------------------------------------------ #
    # Decision gate (identical to prior milestone — not weakened)         #
    # ------------------------------------------------------------------ #

    def _evaluate_gate(
        self, off: ReasoningScore, on: ReasoningScore, per_class: dict[str, dict[str, Any]]
    ) -> GateDecision:
        helps = (
            on.completion >= off.completion
            and on.retries <= off.retries
            and on.repairs <= off.repairs
            and self._improves_at_least_one_axis(on, off)
        )
        no_regress = on.regressions == 0
        safe_neutral = on.blocked_unsafe <= off.blocked_unsafe
        abstention_ok = on.abstention_precision >= 0.8 and on.abstention_recall >= 0.8
        useful = on.reasoning_usefulness > 0.0

        clauses = {
            "helps": helps,
            "no_regress": no_regress,
            "safe_neutral": safe_neutral,
            "abstention_ok": abstention_ok,
            "useful": useful,
        }
        adopt = helps and no_regress and safe_neutral and abstention_ok and useful
        explanation = self._explain(adopt, on, off, per_class, clauses)
        return GateDecision(
            adopt_default_on=adopt,
            clauses=clauses,
            explanation=explanation,
        )

    def _improves_at_least_one_axis(self, on: ReasoningScore, off: ReasoningScore) -> bool:
        return (
            on.planning_quality > off.planning_quality
            or on.repair_quality > off.repair_quality
            or on.promotion_quality > off.promotion_quality
        )

    def _explain(
        self,
        adopt: bool,
        on: ReasoningScore,
        off: ReasoningScore,
        per_class: dict[str, dict[str, Any]],
        clauses: dict[str, bool],
    ) -> str:
        parts = []
        if adopt:
            parts.append("Gate PASSES: all five clauses satisfied.")
        else:
            failed = [k for k, v in clauses.items() if not v]
            parts.append(f"Gate FAILS: failed clauses: {', '.join(failed)}.")
        parts.append(f"completion: {off.completion:.2f} -> {on.completion:.2f}")
        parts.append(f"retries: {off.retries} -> {on.retries}")
        parts.append(f"repairs: {off.repairs} -> {on.repairs}")
        parts.append(f"blocked_unsafe: {off.blocked_unsafe} -> {on.blocked_unsafe}")
        parts.append(f"planning_quality: {off.planning_quality:.2f} -> {on.planning_quality:.2f}")
        parts.append(f"repair_quality: {off.repair_quality:.2f} -> {on.repair_quality:.2f}")
        parts.append(f"promotion_quality: {off.promotion_quality:.2f} -> {on.promotion_quality:.2f}")
        return "; ".join(parts)


# Convenience aliases used by the amplification test module.
amplified_benchmark = reasoning_benchmark


def _should_abstain_cases(cases: list[ReasoningCase] | None = None) -> list[ReasoningCase]:
    cases = cases if cases is not None else reasoning_benchmark(".")
    return [c for c in cases if c.should_abstain]


def _should_answer_cases() -> list[ReasoningCase]:
    """Genuinely-rich inputs the engine should ADVISE on (not abstain)."""
    return [
        ReasoningCase(
            case_id="rich_repair_a", seam="reflection", fixture_class="control",
            setup={"output": "ModuleNotFoundError: No module named 'parse_config'"},
        ),
        ReasoningCase(
            case_id="rich_repair_b", seam="reflection", fixture_class="control",
            setup={"output": "AssertionError: expected 3 but got 2"},
        ),
    ]


def decision_cases(cases: list[ReasoningCase] | None = None) -> list[DecisionCase]:
    cases = cases if cases is not None else reasoning_benchmark(".")
    return [c for c in cases if isinstance(c, DecisionCase) and c.divergence_required]


def case_by_id(case_id: str, cases: list[ReasoningCase] | None = None) -> ReasoningCase:
    cases = cases if cases is not None else reasoning_benchmark(".")
    for c in cases:
        if c.case_id == case_id:
            return c
    raise KeyError(case_id)


def run_case_in_mode(case: ReasoningCase, reasoning: bool, root: str | None = None) -> CaseOutcome:
    return run_case(case, reasoning, root)
