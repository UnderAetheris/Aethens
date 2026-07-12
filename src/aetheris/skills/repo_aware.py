"""Repo-Aware Coding Skills v0 — data-only skill template + read-only renderer.

The skill is inert data: it *declares* which repository facts it needs (a
``FactRequest`` manifest) and whether it wants advisory reasoning.  A separate
``RepoAwareSkillRenderer`` is the only component that touches the read-only
Understanding / Reasoning views; it resolves the declared blanks and emits an
ordinary, validated ``MultiStepPlan`` that runs through the exact same spine
(planner -> executive -> Reflection -> SafetyLayer -> tools).  No new execution
path, no widened authority.  Smarter *content*, identical *shape*.

Three deterministic fallback layers keep a repo-aware skill never worse than
its plain twin:
  1. Reasoning abstains / not consulted / single candidate -> default shape.
  2. Understanding has no answer for a declared fact -> that blank falls back
     to its declared ``FactRequest.default`` (the pre-Understanding behavior).
  3. Skill doesn't match the task at all -> the planner plans exactly as today.
"""
from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..planner.plan import MultiStepPlan, PlanStep
from ..skills.registry import SkillStep, SkillTemplate
from ..understanding.engine import RepoUnderstanding


# Every step a repo-aware skill may emit must be an existing gated tool.  The
# renderer refuses anything else, so a rendered plan can never introduce a new
# execution path.
REPO_AWARE_TOOLS: tuple[str, ...] = (
    "edit_file", "write_file", "read_file", "list_dir", "shell", "echo",
)


@dataclass(frozen=True)
class SkillMatcher:
    """When does a repo-aware skill apply? Unchanged conservative trigger logic."""

    trigger_patterns: tuple[str, ...]
    required_params: tuple[str, ...] = ()

    def matches(self, task: str) -> bool:
        low = task.lower()
        return any(re.search(p, low, re.IGNORECASE) for p in self.trigger_patterns)

    def extract_params(self, task: str) -> dict[str, str] | None:
        params: dict[str, str] = {}
        for param in self.required_params:
            m = re.search(rf"{re.escape(param)}=(\S+)", task)
            if m:
                params[param] = m.group(1)
        if all(p in params for p in self.required_params):
            return params
        return None


@dataclass(frozen=True)
class FactRequest:
    """A labeled blank the renderer fills from Repository Understanding.

    Data only: names the query and the task parameter that drives it.  Holds
    no handle, calls nothing.
    """

    binding: str          # the template parameter this fact fills, e.g. "import_module"
    query: str            # exporting_module | find_helper | dependents_of |
                          # tests_for | module_of | exported_api
    arg_from: str         # which task param drives the query, e.g. "symbol" or "path"
    default: str | None = None   # deterministic fallback if Understanding has no answer


@dataclass(frozen=True)
class CandidateShape:
    """One possible plan shape the skill can render.

    A skill may declare more than one; the renderer picks the default (or, if
    declared, the shape whose ``requires_binding`` got a real fact) or, when
    reasoning is consulted and recommends a shape id, that one.
    """

    shape_id: str
    steps: tuple[SkillStep, ...]      # ordinary gated-tool steps, with {binding} blanks
    is_default: bool = False          # the deterministic floor
    requires_binding: str | None = None  # when set, pick this shape if that binding got a real fact


@dataclass(frozen=True)
class RepoAwareSkill:
    """Data-only. Holds NO query handle, NO engine, NO tool. Declares needs."""

    name: str
    version: int
    match: SkillMatcher                 # unchanged: when does this skill apply
    facts_needed: tuple[FactRequest, ...] = ()
    consult_reasoning: bool = False      # ask for advice before rendering?
    candidates: tuple[CandidateShape, ...] = ()   # >=1; exactly one is_default=True
    plan_source: str = "repo_aware_skill"

    def default_shape(self) -> CandidateShape:
        return next(c for c in self.candidates if c.is_default)


@dataclass(frozen=True)
class FactUse:
    """One resolved fact declaration, for structured journaling."""

    query: str
    arg: str | None
    answer: str | None
    fallback: bool


def _resolve_answer(understanding: Any, query: str, arg: str | None) -> str | None:
    """Run one read-only Understanding query; return a string or None.

    ``query == "param"`` is a passthrough: bind the raw task parameter value
    (e.g. a file path) without consulting Understanding.

    Unknown symbols / missing helpers -> None (caller falls back to default).
    Lists (helpers, dependents, tests) reduce to their first element's name.
    """
    if query == "param":
        return arg
    if understanding is None or arg is None:
        return None
    try:
        method = getattr(understanding, query, None)
        if method is None:
            return None
        result = method(arg)
    except Exception:
        return None
    if result is None:
        return None
    if isinstance(result, str):
        return result or None
    if isinstance(result, (list, tuple)):
        if not result:
            return None
        first = result[0]
        return getattr(first, "name", None) or (first if isinstance(first, str) else None)
    return str(result)


class RepoAwareSkillRenderer:
    """The ONLY component that touches the read-only Understanding/Reasoning
    views on a skill's behalf.  Resolves declarations and emits a standard,
    validated ``MultiStepPlan``.  Holds no tool handle and no SafetyLayer.
    """

    def __init__(
        self,
        understanding: Any = None,        # read-only RepoUnderstanding view
        reasoning: Any = None,            # ReasoningEngine | None => not consulted
    ) -> None:
        self._u = understanding
        self._r = reasoning
        self._journal: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def render(self, skill: RepoAwareSkill, task: str, task_id: str = "task1") -> MultiStepPlan:
        params = skill.match.extract_params(task) or {}
        # 1) resolve declared facts from read-only Understanding (per-blank fallback)
        bindings: dict[str, str] = {}
        real_bindings: set[str] = set()
        used_facts: list[FactUse] = []
        for req in skill.facts_needed:
            arg = params.get(req.arg_from)
            answer = _resolve_answer(self._u, req.query, arg)
            if answer is not None:
                bindings[req.binding] = answer
                real_bindings.add(req.binding)
                used_facts.append(FactUse(req.query, arg, answer, fallback=False))
            else:
                bindings[req.binding] = req.default if req.default is not None else ""
                used_facts.append(FactUse(req.query, arg, None, fallback=True))

        # 2) choose a candidate shape (default / fact-driven / reasoning-advised)
        chosen, advice = self._choose_shape(skill, task, bindings, real_bindings)

        # 3) render the chosen shape's steps into concrete gated steps
        plan = self._materialize(chosen, bindings, task, task_id, skill)

        # 4) journal what facts were used + whether reasoning helped/abstained
        self._journal_render(skill, used_facts, advice, chosen, plan)
        return plan

    def render_history(self) -> list[dict[str, Any]]:
        return list(self._journal)

    # ------------------------------------------------------------------ #
    # Shape selection                                                     #
    # ------------------------------------------------------------------ #

    def _choose_shape(
        self, skill: RepoAwareSkill, task: str, bindings: dict[str, str], real_bindings: set[str]
    ) -> tuple[CandidateShape, Any]:
        default = skill.default_shape()
        # (1) facts win: a non-default shape whose required fact actually
        # resolved (not fell back to default) is preferred.  Facts are certain;
        # reasoning is only advisory, so fact-driven shapes take precedence.
        if len(skill.candidates) > 1:
            for c in skill.candidates:
                if not c.is_default and c.requires_binding in real_bindings:
                    return c, None
        # (2) reasoning advisory (bounded, may abstain, never required)
        if skill.consult_reasoning and self._r is not None and len(skill.candidates) > 1:
            advice = self._r.deliberate_for_planning(
                type(
                    "Ctx", (), {
                        "task": task,
                        "understanding_facts": bindings,
                        "candidate_shapes": tuple(c.shape_id for c in skill.candidates),
                    }
                )()
            )
            if not getattr(advice, "abstained", False) and getattr(advice, "recommended_approach", None) in {
                c.shape_id for c in skill.candidates
            }:
                chosen = next(
                    c for c in skill.candidates if c.shape_id == advice.recommended_approach
                )
                return chosen, advice
            return default, advice
        return default, None

    # ------------------------------------------------------------------ #
    # Materialization + validation                                        #
    # ------------------------------------------------------------------ #

    def _materialize(
        self,
        shape: CandidateShape,
        bindings: dict[str, str],
        task: str,
        task_id: str,
        skill: RepoAwareSkill,
    ) -> MultiStepPlan:
        steps: list[PlanStep] = []
        for st in shape.steps:
            arg = SkillTemplate._substitute(st.arg_template, bindings)
            if st.tool not in REPO_AWARE_TOOLS:
                # never emit an unknown/ungated tool; degrade to the default shape
                return self._materialize(skill.default_shape(), bindings, task, task_id, skill)
            steps.append(
                PlanStep(
                    tool=st.tool,
                    arg=arg,
                    reason=f"[repo_aware:{skill.name}] {st.reason}",
                    depends_on=list(st.depends_on),
                )
            )
        plan = MultiStepPlan(
            task_id=task_id,
            steps=steps,
            task=task,
            plan_source=f"{skill.plan_source}:{skill.name}@{skill.version}:{shape.shape_id}",
        )
        # validate DAG integrity (no malformed plan can be produced)
        if not plan.is_valid_dag():
            raise ValueError("repo-aware skill produced an invalid plan DAG")
        return plan

    def _journal_render(
        self,
        skill: RepoAwareSkill,
        used_facts: list[FactUse],
        advice: Any,
        chosen: CandidateShape,
        plan: MultiStepPlan,
    ) -> None:
        reasoning_record = None
        if advice is not None:
            reasoning_record = {
                "consulted": True,
                "abstained": bool(getattr(advice, "abstained", False)),
                "helped": not getattr(advice, "abstained", False)
                and getattr(advice, "recommended_approach", None) == chosen.shape_id,
                "chosen_shape": chosen.shape_id,
                "confidence": round(getattr(advice, "confidence", 0.0), 3),
            }
        self._journal.append(
            {
                "skill": skill.name,
                "version": skill.version,
                "plan_source": plan.plan_source,
                "facts_used": [
                    {
                        "query": f.query,
                        "arg": f.arg,
                        "answer_or_default": f.answer if not f.fallback else f"default:{f.answer}",
                    }
                    for f in used_facts
                ],
                "reasoning": reasoning_record,
                "rendered_plan_id": plan.task_id,
                "timestamp": time.time(),
            }
        )


# ---------------------------------------------------------------------------
# Understanding-backed fixtures (hermetic, deterministic) for the skills
# ---------------------------------------------------------------------------


def _understanding_from_fixtures(root: Path, fixtures: dict[str, str]) -> RepoUnderstanding:
    for rel, content in fixtures.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    model_path = root / "model.json"
    u = RepoUnderstanding(root=str(root), model_path=str(model_path))
    u.scan()
    return u
