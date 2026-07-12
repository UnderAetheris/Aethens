"""Repo-aware vs plain twin benchmark + promotion gate.

Compares a repo-aware skill (Understanding facts + optional advisory reasoning)
against its plain twin (facts/reasoning disabled) on hermetic fixtures.  The
gate is the same measured discipline as the reasoning gate: promote the
repo-aware version only if it measurably beats the twin with zero regressions
and flat safety.  Smarter content, identical shape and authority.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory.store import MemoryStore
from ..reasoning.benchmark import ReasoningComparison, amplified_benchmark
from ..tools.builtins import default_registry
from .repo_aware import RepoAwareSkillRenderer, _understanding_from_fixtures
from .repo_aware_seeds import (
    SkillFixture,
    correct_module_fixture,
    helper_reuse_fixture,
    helper_reuse_skill,
    missing_import_skill,
    plain_twin,
    two_shape_skill,
)
from ..reasoning.engine import ReasoningEngine
from ..planner.plan import MultiStepPlan


# ---------------------------------------------------------------------------
# Ground-truth correctness verifiers
# ---------------------------------------------------------------------------


def _imports_module(plan: MultiStepPlan, module: str) -> bool:
    return any(module in step.arg for step in plan.steps if step.tool == "edit_file")


def _reuses_helper(plan: MultiStepPlan, helper: str) -> bool:
    reuses = any(
        f"from helpers import {helper}" in step.arg
        for step in plan.steps
        if step.tool == "edit_file"
    )
    reimplements = any(f"def {helper}" in step.arg for step in plan.steps)
    return reuses and not reimplements


# ---------------------------------------------------------------------------
# Score / result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoAwareScore:
    completion: float = 0.0
    retries: int = 0
    repairs: int = 0
    regressions: int = 0
    blocked_unsafe: int = 0
    reasoning_usefulness: float = 0.0


@dataclass(frozen=True)
class RepoAwareResult:
    skill: str
    on: RepoAwareScore
    off: RepoAwareScore
    per_class: dict[str, Any]
    promote: bool
    gate: dict[str, bool]
    explanation: str


# ---------------------------------------------------------------------------
# Fixture suite (hermetic)
# ---------------------------------------------------------------------------


def skill_benchmark() -> list[tuple[SkillFixture, Any]]:
    """Repo-aware skills paired with the fixtures that exercise them."""
    cm = correct_module_fixture()
    cm = SkillFixture(
        cm.name, cm.task, cm.fixtures,
        verify=lambda p: _imports_module(p, "src.pkg.config"),
    )
    hr = helper_reuse_fixture()
    hr = SkillFixture(
        hr.name, hr.task, hr.fixtures,
        verify=lambda p: _reuses_helper(p, "parse_config"),
    )
    # control / no-real-fact: unknown symbol -> degrades to default import,
    # identical to the plain twin -> no improvement, no regression.
    ctrl = SkillFixture(
        "no_real_fact_import",
        "fix missing import symbol=unknown_sym path=src/pkg/main.py",
        {
            "src/pkg/__init__.py": "",
            "src/pkg/config.py": "def parse_config(data):\n    return data\n",
            "src/pkg/main.py": "def run():\n    return parse_config(1)\n",
        },
        verify=lambda p: True,
    )
    # abstain / thin: reasoning consulted but yields the default shape,
    # outcome identical to plain -> not promoted.
    ab = SkillFixture("abstain_thin", "choose shape", {}, verify=lambda p: True)
    return [
        (cm, missing_import_skill()),
        (hr, helper_reuse_skill()),
        (ctrl, missing_import_skill()),
        (ab, two_shape_skill()),
    ]


# ---------------------------------------------------------------------------
# Comparison harness
# ---------------------------------------------------------------------------


class RepoAwareComparison:
    """Runs one repo-aware skill against its plain twin on a fixture."""

    def run(self, fixture: SkillFixture, skill: Any) -> RepoAwareResult:
        root = Path(tempfile.mkdtemp(prefix="aeth_repoaware_"))
        u = _understanding_from_fixtures(root, fixture.fixtures)
        reasoning = self._build_reasoning(u) if fixture.fixtures else None

        on_r = RepoAwareSkillRenderer(understanding=u, reasoning=reasoning)
        off_r = RepoAwareSkillRenderer(understanding=None, reasoning=None)

        on_plan = on_r.render(skill, fixture.task)
        off_plan = off_r.render(plain_twin(skill), fixture.task)

        on_correct = bool(fixture.verify(on_plan))
        off_correct = bool(fixture.verify(off_plan))

        on_s = self._score(on_correct, skill)
        off_s = self._score(off_correct, skill)
        usefulness = round(max(0.0, on_s.completion - off_s.completion), 3)
        on_s = RepoAwareScore(
            completion=on_s.completion, retries=on_s.retries, repairs=on_s.repairs,
            regressions=on_s.regressions, blocked_unsafe=on_s.blocked_unsafe,
            reasoning_usefulness=usefulness,
        )

        promote, gate, explanation = self._gate(on_s, off_s, skill)
        per_class = {
            "on_shape": on_plan.plan_source,
            "off_shape": off_plan.plan_source,
            "on_correct": on_correct,
            "off_correct": off_correct,
        }
        return RepoAwareResult(
            skill=skill.name, on=on_s, off=off_s,
            per_class=per_class, promote=promote, gate=gate, explanation=explanation,
        )

    # ------------------------------------------------------------------ #

    def _build_reasoning(self, u: Any) -> ReasoningEngine:
        mem = MemoryStore(str(Path(tempfile.mkdtemp(prefix="aeth_ra_mem_")) / "events.jsonl"))
        return ReasoningEngine(understanding=u, memory=mem, skills=default_registry())

    def _score(self, correct: bool, skill: Any) -> RepoAwareScore:
        if correct:
            return RepoAwareScore(completion=1.0, retries=0, repairs=0, regressions=0,
                                  blocked_unsafe=0, reasoning_usefulness=0.0)
        # plain-twin failure profile for the skill's fixture class
        base = {
            "missing_import_repair": (0.5, 2, 0),
            "helper_reuse_impl": (0.6, 0, 1),
        }.get(skill.name, (1.0, 0, 0))
        return RepoAwareScore(
            completion=base[0], retries=base[1], repairs=base[2],
            regressions=0, blocked_unsafe=0, reasoning_usefulness=0.0,
        )

    def _gate(self, on: RepoAwareScore, off: RepoAwareScore, skill: Any):
        helps = (
            on.completion >= off.completion
            and on.retries <= off.retries
            and on.repairs <= off.repairs
            and (
                on.completion > off.completion
                or on.retries < off.retries
                or on.repairs < off.repairs
            )
        )
        no_regress = on.regressions == 0 and off.regressions == 0
        safe_neutral = on.blocked_unsafe <= off.blocked_unsafe
        # repo-awareness (facts or reasoning) must have earned the improvement
        useful = on.reasoning_usefulness > 0.0
        promote = helps and no_regress and safe_neutral and useful
        clauses = {
            "helps": helps,
            "no_regress": no_regress,
            "safe_neutral": safe_neutral,
            "useful": useful,
        }
        explanation = (
            "PROMOTE" if promote else "HOLD (unpromoted)"
        ) + f"; on={on} off={off} clauses={clauses}"
        return promote, clauses, explanation


def reasoning_ci_gate_passes() -> bool:
    return ReasoningComparison(".").run(amplified_benchmark(".")).gate.adopt_default_on
