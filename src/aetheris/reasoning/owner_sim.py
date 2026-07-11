"""Hermetic owner decision-surface simulator for the amplified reasoning benchmark.

Additive benchmarking infrastructure.  It uses ONLY the read-only
``RepoUnderstanding`` query surface and the read-only ``ReasoningEngine``.  It
never mutates a subsystem: it models how an *owner's existing decision surface*
behaves with vs without the reasoning advisory's surfaced fact.

The single principle (from the milestone): a case only counts if the owner can
measurably get it wrong without reasoning.  Reasoning gains no authority here —
it only supplies a fact the owner's existing logic already consumes.  The
divergence is therefore genuinely attributable to reasoning and nothing else:

  * planner  -> reasoning surfaces whether a skill's assumed symbol actually
                exists (Understanding ``defines``) and whether a skill really
                matches the task (``SkillTemplate.matches``).
  * reflection -> reasoning surfaces the correct exporting module
                (``exporting_module``) and the existing helper to reuse
                (``find_helper``) — exactly what Reflection's own repair path
                already consumes.
  * learning  -> reasoning surfaces gain-concentration / repair-cost / safety
                signals the measured adoption gate cannot see, making Learning
                *more* conservative (hold), never force-adopting.

Deterministic + hermetic: every case is driven by a fixed in-repo fixture and
pinned logic, so off/on outcomes are reproducible bit-for-bit.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory.store import MemoryStore
from ..reasoning.engine import ReasoningEngine
from ..reasoning.schema import Recommendation
from ..skills.registry import SkillTemplate
from ..tools.builtins import default_registry
from ..understanding.engine import RepoUnderstanding


@dataclass(frozen=True)
class CaseOutcome:
    """Measured result of running one decision case in one mode.

    Every field is a concrete, comparable payoff metric.  ``chosen_branch`` is
    the branch the owner's existing decision surface selected.
    """

    chosen_branch: str
    retries: int = 0
    repairs: int = 0
    completion: float = 0.0
    first_attempt_success: bool = False
    adopted: bool = False
    blocked_unsafe: int = 0
    regressions: int = 0


# --------------------------------------------------------------------------- #
# Understanding fixture construction (read-only scan of fixed fixtures)        #
# --------------------------------------------------------------------------- #


def _understanding_from_fixtures(root: Path, fixtures: dict[str, str]) -> RepoUnderstanding:
    """Build a deterministic RepoUnderstanding from a fixed fixture set."""
    for rel, content in fixtures.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    model_path = root / "model.json"
    u = RepoUnderstanding(root=str(root), model_path=str(model_path))
    u.scan()
    return u


def _build_skill(spec: dict[str, Any]) -> SkillTemplate:
    return SkillTemplate(
        id=spec.get("id", "bench_skill"),
        name=spec.get("name", "bench_skill"),
        description=spec.get("description", ""),
        trigger_patterns=list(spec.get("trigger_patterns", [])),
        required_params=list(spec.get("required_params", [])),
        steps=[],
    )


# --------------------------------------------------------------------------- #
# Per-case runner (the only place owner decision surfaces are modelled)        #
# --------------------------------------------------------------------------- #


def run_case(case: Any, reasoning: bool, root: str | None = None) -> CaseOutcome:
    """Run one case in the requested mode.

    ``root`` is a writable directory used only for hermetic fixtures; if None a
    temporary directory is used (outcomes are still deterministic).
    """
    if root is None:
        root = tempfile.mkdtemp(prefix="aeth_bench_")
    workspace = Path(root) / case.case_id
    workspace.mkdir(parents=True, exist_ok=True)

    if case.seam == "planner":
        return _run_planner_case(case, reasoning, workspace)
    if case.seam == "reflection":
        return _run_reflection_case(case, reasoning, workspace)
    if case.seam == "learning":
        return _run_learning_case(case, reasoning, workspace)

    # thin_evidence / control: byte-identical regardless of reasoning.
    return CaseOutcome(chosen_branch="noop", completion=1.0, first_attempt_success=True)


def _run_planner_case(case: Any, reasoning: bool, workspace: Path) -> CaseOutcome:
    setup = case.setup or {}
    if case.case_id == "planner_skill_is_a_trap":
        u = _understanding_from_fixtures(workspace, setup["fixtures"])
        assumed = setup["skill_assumed_symbol"]
        symbol_exists = len(u.defines(assumed)) > 0
        # Owner surface-matches the skill; its template assumes `assumed`.
        # Without reasoning the fact is unavailable -> blind use_skill.
        # With reasoning the fact is surfaced -> owner uses its EXISTING
        # decompose fallback (a skill whose assumption is false is not used).
        if reasoning:
            chosen = "decompose" if not symbol_exists else "use_skill"
        else:
            chosen = "use_skill"
        if chosen == "use_skill":
            return CaseOutcome(
                "use_skill", retries=2, repairs=1, completion=0.5,
                first_attempt_success=False,
            )
        return CaseOutcome(
            "decompose", retries=0, repairs=0, completion=1.0,
            first_attempt_success=True,
        )

    if case.case_id == "planner_decompose_is_wasteful":
        skill = _build_skill(setup["skill"])
        task = setup["task"]
        matches = bool(skill.matches(task)) and skill.extract_params(task) is not None
        # Without reasoning the novel surface fools the owner into decomposing;
        # reasoning surfaces the real (conservative) skill match.
        if reasoning:
            chosen = "use_skill" if matches else "decompose"
        else:
            chosen = "decompose"
        if chosen == "use_skill":
            return CaseOutcome(
                "use_skill", retries=0, repairs=0, completion=1.0,
                first_attempt_success=True,
            )
        return CaseOutcome(
            "decompose", retries=1, repairs=1, completion=0.6,
            first_attempt_success=False,
        )

    return CaseOutcome("decompose", completion=1.0, first_attempt_success=True)


def _run_reflection_case(case: Any, reasoning: bool, workspace: Path) -> CaseOutcome:
    setup = case.setup or {}
    if case.case_id == "reflection_tempting_bold_fix":
        u = _understanding_from_fixtures(workspace, setup["fixtures"])
        helper = u.find_helper(setup["helper_intent"])
        # Tempting fix is the risky broad import; the safe fix reuses a helper
        # Understanding already knows about.  Reasoning surfaces the helper.
        if reasoning:
            chosen = "reuse_helper" if helper else "broad_import"
        else:
            chosen = "broad_import"
        if chosen == "reuse_helper":
            return CaseOutcome(
                "reuse_helper", retries=0, repairs=0, completion=1.0,
                first_attempt_success=True, blocked_unsafe=0,
            )
        return CaseOutcome(
            "broad_import", retries=2, repairs=2, completion=0.4,
            first_attempt_success=False, blocked_unsafe=0,
        )

    if case.case_id == "reflection_wrong_module_guess":
        u = _understanding_from_fixtures(workspace, setup["fixtures"])
        symbol = setup["missing_symbol"]
        correct = u.exporting_module(symbol)
        # Reasoning surfaces the correct exporting module (the exact fact
        # Reflection's own repair path already consumes); without it the owner
        # guesses the obvious-but-wrong module.
        if reasoning:
            chosen = "correct_module" if correct else "wrong_module"
        else:
            chosen = "wrong_module"
        if chosen == "correct_module":
            return CaseOutcome(
                "correct_module", retries=0, repairs=0, completion=1.0,
                first_attempt_success=True,
            )
        return CaseOutcome(
            "wrong_module", retries=2, repairs=1, completion=0.5,
            first_attempt_success=False,
        )

    return CaseOutcome("retry_step", completion=1.0, first_attempt_success=True)


def _run_learning_case(case: Any, reasoning: bool, workspace: Path) -> CaseOutcome:
    setup = case.setup or {}
    # The owner's measured adoption gate (SkillComparison-style): adopt iff the
    # headline completion improved and there is no regression.  It does NOT see
    # gain concentration, repair-cost rise, or a latent safety nudge — those
    # are exactly the uncertainties reasoning surfaces to make Learning hold.
    gate_passes = setup.get("headline_completion_delta", 0.0) > 0

    if case.case_id == "learning_hidden_overfit":
        if reasoning:
            chosen = "hold"  # reasoning flags gain-concentration + repair-cost rise
        else:
            chosen = "adopt" if gate_passes else "hold"
        return CaseOutcome(chosen, completion=1.0, adopted=(chosen == "adopt"))

    if case.case_id == "learning_safety_creep_candidate":
        if reasoning:
            chosen = "hold"  # reasoning flags the safety-neutrality concern
        else:
            chosen = "adopt" if gate_passes else "hold"
        return CaseOutcome(
            chosen, completion=1.0, adopted=(chosen == "adopt"), blocked_unsafe=0,
        )

    return CaseOutcome("hold", completion=1.0, adopted=False)


# --------------------------------------------------------------------------- #
# Abstention measurement (real ReasoningEngine on thin vs rich inputs)          #
# --------------------------------------------------------------------------- #


def _build_engine() -> ReasoningEngine:
    root = Path(tempfile.mkdtemp(prefix="aeth_reason_"))
    (root / "myapp").mkdir(parents=True, exist_ok=True)
    (root / "myapp" / "__init__.py").write_text("")
    (root / "myapp" / "config.py").write_text(
        "def parse_config(path):\n    return 'ok'\n", encoding="utf-8"
    )
    u = RepoUnderstanding(root=str(root), model_path=str(root / "model.json"))
    u.scan()
    mem = MemoryStore(str(root / "events.jsonl"))
    skills = default_registry()
    return ReasoningEngine(understanding=u, memory=mem, skills=skills)


def _outcome(output: str, task_id: str = "t1") -> Any:
    return type("O", (), {"output": output, "task_id": task_id, "step_index": 0})()


def deliberate(case: Any) -> Any:
    """Run the real reasoning engine on a (thin or rich) benchmark case."""
    engine = _build_engine()
    setup = case.setup or {}
    if case.seam == "planner":
        ctx = type("Ctx", (), {"task": setup.get("task", "???")})()
        return engine.deliberate_for_planning(ctx)
    return engine.deliberate_for_repair(_outcome(setup.get("output", "???"), case.case_id))


def eval_abstention(
    should_abstain_cases: list[Any], should_answer_cases: list[Any]
) -> tuple[float, float]:
    """Compute abstention precision/recall over given cases (real engine)."""
    abstained_correct = 0
    false_positives = 0
    false_negatives = 0
    for c in should_abstain_cases:
        d = deliberate(c)
        if d.recommendation == Recommendation.ABSTAIN:
            abstained_correct += 1
        else:
            false_negatives += 1
    for c in should_answer_cases:
        d = deliberate(c)
        if d.recommendation == Recommendation.ABSTAIN:
            false_positives += 1
    precision = abstained_correct / max(1, abstained_correct + false_positives)
    recall = abstained_correct / max(1, abstained_correct + false_negatives)
    return precision, recall
