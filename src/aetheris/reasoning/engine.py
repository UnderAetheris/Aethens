"""Deliberative Reasoning Engine v0.

Read-only deliberator.  Consumes knowledge, produces a Deliberation.
Has NO SafetyLayer, NO ToolSystem, NO planner mutator, NO executive,
NO write handle.  It cannot cause an effect.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .schema import (
    Assumption,
    CandidateApproach,
    Consequence,
    Deliberation,
    Observation,
    Provenance,
    Recommendation,
    Risk,
    Seam,
    Uncertainty,
)


@dataclass(frozen=True)
class ReasoningBudget:
    max_depth: int = 2
    max_hypotheses: int = 4
    timeout_ms: int = 750
    max_fan_in: int = 64
    confidence_floor: float = 0.60


@dataclass
class Deadline:
    """Soft + hard wall-clock deadline."""

    timeout_ms: int
    _start: float = field(default_factory=time.time, repr=False)

    def expired(self) -> bool:
        return (time.time() - self._start) * 1000 >= self.timeout_ms * 0.8

    def expired_hard(self) -> bool:
        return (time.time() - self._start) * 1000 >= self.timeout_ms


@dataclass
class _ReasonInputs:
    """Internal bundle of everything reasoning may consult."""
    understanding: Any = None      # RepoUnderstanding query view
    memory: Any = None             # read-only memory
    skills: Any = None             # read-only skill registry
    task_context: Any = None       # PlannerContext or similar
    failure_context: Any = None    # ReflectionOutcome or similar
    promotion_context: Any = None  # PromotionCandidate or similar


class ReasoningEngine:
    """Read-only deliberator.  Produces immutable Deliberation objects.

    The engine is constructed with read-only handles only.  It has no
    SafetyLayer, no ToolSystem, no executive, no planner mutator.
    """

    def __init__(
        self,
        understanding: Any = None,
        memory: Any = None,
        skills: Any = None,
        budget: ReasoningBudget | None = None,
        model: Any = None,
    ) -> None:
        self._u = understanding
        self._mem = memory
        self._skills = skills
        self._budget = budget or ReasoningBudget()
        self._model = model
        self._journal: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Public seam entrypoints (pull-only; owner calls, owner receives)   #
    # ------------------------------------------------------------------ #

    def deliberate_for_planning(self, ctx: Any) -> Deliberation:
        """Advise on plan shape.  Planner still owns the MultiStepPlan."""
        inputs = _ReasonInputs(
            understanding=self._u,
            memory=self._mem,
            skills=self._skills,
            task_context=ctx,
        )
        return self._deliberate(Seam.PLANNER, subject=_subject_of(ctx), inputs=inputs)

    def deliberate_for_repair(self, outcome: Any) -> Deliberation:
        """Advise on repair approach.  Reflection still owns the verdict."""
        inputs = _ReasonInputs(
            understanding=self._u,
            memory=self._mem,
            skills=self._skills,
            failure_context=outcome,
        )
        return self._deliberate(Seam.REFLECTION, subject=_subject_of(outcome), inputs=inputs)

    def deliberate_for_promotion(self, candidate: Any) -> Deliberation:
        """Advise on promotion go/no-go.  Learning still owns adoption."""
        inputs = _ReasonInputs(
            understanding=self._u,
            memory=self._mem,
            skills=self._skills,
            promotion_context=candidate,
        )
        return self._deliberate(Seam.LEARNING, subject=_subject_of(candidate), inputs=inputs)

    # ------------------------------------------------------------------ #
    # Shared bounded deliberation core                                    #
    # ------------------------------------------------------------------ #

    def _deliberate(self, seam: Seam, subject: str, inputs: _ReasonInputs) -> Deliberation:
        clock = Deadline(self._budget.timeout_ms)

        observations = self._gather_observations(inputs)
        assumptions = self._surface_assumptions(inputs, observations)
        uncertainties = self._surface_uncertainties(observations)

        candidates = self._enumerate_candidates(inputs, observations)
        candidates = candidates[: self._budget.max_hypotheses]
        candidates = self._score_candidates(candidates, observations, assumptions)

        if self._model is not None and not clock.expired():
            candidates = self._maybe_enrich_with_model(candidates, inputs, clock)

        risks = self._assess_risks(candidates, inputs)
        consequences = self._predict_consequences(candidates, inputs)

        depth = 0
        while depth < self._budget.max_depth and not clock.expired():
            refined = self._refine(candidates, risks, uncertainties)
            if refined is None:
                break
            candidates, risks = refined
            depth += 1

        confidence = self._compute_confidence(candidates, observations, uncertainties, risks)
        best = self._best_candidate(candidates)

        if confidence < self._budget.confidence_floor or best is None or clock.expired_hard():
            return self._abstain(
                seam, subject, observations, uncertainties, confidence, depth,
                reason=self._abstain_reason(confidence, clock, uncertainties),
            )

        deliberation = Deliberation(
            seam=seam,
            subject=subject,
            assumptions=tuple(assumptions),
            observations=tuple(observations),
            uncertainties=tuple(uncertainties),
            candidates=tuple(candidates),
            risks=tuple(risks),
            consequences=tuple(consequences),
            confidence=confidence,
            recommendation=self._recommendation_for(best, risks),
            recommended_approach=best.approach_id,
            depth_used=depth,
            hypotheses_used=len(candidates),
            abstained=False,
            reason=self._explain(best, risks),
        )
        self._journal_append(deliberation)
        return deliberation

    # ------------------------------------------------------------------ #
    # Observation / assumption / uncertainty gathering                    #
    # ------------------------------------------------------------------ #

    def _gather_observations(self, inputs: _ReasonInputs) -> list[Observation]:
        """Collect observations from Understanding, memory, skills, and context."""
        observations: list[Observation] = []
        count = 0

        if inputs.understanding is not None:
            try:
                facts = inputs.understanding.project_facts()
                if facts:
                    observations.append(Observation(
                        statement=f"project: {facts.get('language', 'python')} / {facts.get('build_system', 'unknown')}",
                        provenance=Provenance(source="understanding", ref="project_facts"),
                    ))
                    count += 1
            except Exception:
                pass

        if inputs.memory is not None:
            try:
                history = inputs.memory.history()
                recent = history[-self._budget.max_fan_in:]
                failure_kinds: dict[str, int] = {}
                for e in recent:
                    kind = e.get("kind", "")
                    if kind in ("step_blocked", "task_blocked", "repair_inserted"):
                        failure_kinds[kind] = failure_kinds.get(kind, 0) + 1
                for kind, cnt in failure_kinds.items():
                    observations.append(Observation(
                        statement=f"recent {kind}: {cnt} occurrences",
                        provenance=Provenance(source="memory", ref=kind),
                    ))
                    count += 1
                    if count >= self._budget.max_fan_in:
                        break
            except Exception:
                pass

        if inputs.skills is not None:
            try:
                active = list(inputs.skills.active_skills())
                observations.append(Observation(
                    statement=f"{len(active)} active skills available",
                    provenance=Provenance(source="skills", ref="registry"),
                ))
            except Exception:
                pass

        return observations[: self._budget.max_fan_in]

    def _surface_assumptions(self, inputs: _ReasonInputs, observations: list[Observation]) -> list[Assumption]:
        assumptions: list[Assumption] = []
        if not observations:
            assumptions.append(Assumption(statement="limited evidence available", load_bearing=True))
        else:
            assumptions.append(Assumption(statement="observations are representative of current repo state", load_bearing=False))
        return assumptions

    def _surface_uncertainties(self, observations: list[Observation]) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = []
        if len(observations) < 2:
            uncertainties.append(Uncertainty(
                question="insufficient observations for confident deliberation",
                resolvable_by="more task history or understanding scan",
            ))
        return uncertainties

    # ------------------------------------------------------------------ #
    # Candidate enumeration and scoring                                   #
    # ------------------------------------------------------------------ #

    def _enumerate_candidates(self, inputs: _ReasonInputs, observations: list[Observation]) -> list[CandidateApproach]:
        candidates: list[CandidateApproach] = []

        seam = self._detect_seam(inputs)
        if seam == Seam.PLANNER:
            candidates.extend([
                CandidateApproach(approach_id="use_matching_skill", summary="Reuse an existing skill if one matches"),
                CandidateApproach(approach_id="decompose_plan", summary="Decompose into verified single-step plans"),
                CandidateApproach(approach_id="inspect_then_plan", summary="Inspect workspace before planning"),
            ])
        elif seam == Seam.REFLECTION:
            candidates.extend([
                CandidateApproach(approach_id="retry_step", summary="Retry the failed step"),
                CandidateApproach(approach_id="repair_and_retry", summary="Insert repair steps then retry"),
                CandidateApproach(approach_id="request_context", summary="Pause and request more context"),
            ])
        elif seam == Seam.LEARNING:
            candidates.extend([
                CandidateApproach(approach_id="adopt", summary="Adopt the candidate"),
                CandidateApproach(approach_id="reject", summary="Reject the candidate"),
                CandidateApproach(approach_id="defer", summary="Defer decision pending more data"),
            ])

        for c in candidates:
            c.score = 0.5

        return candidates

    def _score_candidates(self, candidates: list[CandidateApproach], observations: list[Observation], assumptions: list[Assumption]) -> list[CandidateApproach]:
        for c in candidates:
            support_count = sum(1 for o in observations if c.approach_id.replace("_", " ") in o.statement.lower())
            c.score = min(1.0, 0.5 + support_count * 0.1)
            for a in assumptions:
                if a.load_bearing:
                    c.score *= 0.8
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    # ------------------------------------------------------------------ #
    # Model enrichment (optional, validated)                             #
    # ------------------------------------------------------------------ #

    def _maybe_enrich_with_model(self, candidates: list[CandidateApproach], inputs: _ReasonInputs, clock: Deadline) -> list[CandidateApproach]:
        if self._model is None or clock.expired():
            return candidates
        try:
            enriched = list(candidates)
            model_extra = self._model({"candidates": [c.approach_id for c in candidates]})
            if isinstance(model_extra, dict) and "extra_candidate" in model_extra:
                extra = CandidateApproach(
                    approach_id=model_extra["extra_candidate"],
                    summary=f"model-proposed: {model_extra['extra_candidate']}",
                    score=0.6,
                )
                enriched.append(extra)
            return enriched
        except Exception:
            return candidates

    # ------------------------------------------------------------------ #
    # Risk and consequence assessment                                     #
    # ------------------------------------------------------------------ #

    def _assess_risks(self, candidates: list[CandidateApproach], inputs: _ReasonInputs) -> list[Risk]:
        risks: list[Risk] = []
        for c in candidates:
            if c.approach_id in ("repair_and_retry", "adopt"):
                risks.append(Risk(
                    approach_id=c.approach_id,
                    statement="change may affect dependents",
                    severity="medium",
                    provenance=Provenance(source="reasoning", ref="generic_risk"),
                ))
        return risks

    def _predict_consequences(self, candidates: list[CandidateApproach], inputs: _ReasonInputs) -> list[Consequence]:
        consequences: list[Consequence] = []
        for c in candidates[:2]:
            effect = {
                "retry_step": "no_change",
                "repair_and_retry": "repairs_down",
                "request_context": "no_change",
                "adopt": "repairs_down",
                "reject": "no_change",
                "defer": "no_change",
            }.get(c.approach_id, "no_change")
            consequences.append(Consequence(
                approach_id=c.approach_id,
                predicted=f"predicted effect for {c.approach_id}",
                expected_effect=effect,
            ))
        return consequences

    # ------------------------------------------------------------------ #
    # Refinement, confidence, recommendation                              #
    # ------------------------------------------------------------------ #

    def _refine(self, candidates: list[CandidateApproach], risks: list[Risk], uncertainties: list[Uncertainty]) -> list | None:
        if not candidates:
            return None
        if len(candidates) == 1 and not risks and not uncertainties:
            return None
        for c in candidates:
            for r in risks:
                if r.approach_id == c.approach_id and r.severity == "high":
                    c.score *= 0.7
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates, risks

    def _compute_confidence(self, candidates: list[Observation | Any], observations: list[Observation], uncertainties: list[Uncertainty], risks: list[Risk]) -> float:
        if not candidates:
            return 0.0
        if not observations:
            return 0.2
        base = 0.5
        obs_bonus = min(0.3, len(observations) * 0.05)
        base += obs_bonus
        if len(candidates) >= 2:
            scores = [getattr(c, "score", 0.0) for c in candidates]
            if scores[0] > scores[-1] + 0.2:
                base += 0.1
        for u in uncertainties:
            if u.resolvable_by:
                base -= 0.05
        for r in risks:
            if r.severity == "high":
                base -= 0.15
            elif r.severity == "medium":
                base -= 0.05
        return max(0.0, min(1.0, base))

    def _best_candidate(self, candidates: list[CandidateApproach]) -> CandidateApproach | None:
        if not candidates:
            return None
        return candidates[0]

    def _recommendation_for(self, best: CandidateApproach, risks: list[Risk]) -> Recommendation:
        high_risks = [r for r in risks if r.severity == "high" and r.approach_id == best.approach_id]
        if high_risks:
            return Recommendation.CAUTION
        return Recommendation.PREFER

    def _abstain(self, seam: Seam, subject: str, observations: list[Observation], uncertainties: list[Uncertainty], confidence: float, depth: int, reason: str = "") -> Deliberation:
        return Deliberation(
            seam=seam,
            subject=subject,
            observations=tuple(observations),
            uncertainties=tuple(uncertainties),
            confidence=confidence,
            depth_used=depth,
            hypotheses_used=0,
            abstained=True,
            reason=reason or "confidence below threshold or insufficient evidence",
        )

    def _abstain_reason(self, confidence: float, clock: Deadline, uncertainties: list[Uncertainty]) -> str:
        if clock.expired_hard():
            return "hard timeout reached; abstaining to avoid rushed advice"
        if confidence < self._budget.confidence_floor:
            return f"confidence {confidence:.2f} below floor {self._budget.confidence_floor}"
        if uncertainties:
            return f"unresolved uncertainties: {uncertainties[0].question}"
        return "insufficient evidence"

    def _explain(self, best: CandidateApproach, risks: list[Risk]) -> str:
        risk_summary = ""
        if risks:
            relevant = [r for r in risks if r.approach_id == best.approach_id]
            if relevant:
                risk_summary = f"; risk: {relevant[0].statement} ({relevant[0].severity})"
        return f"prefer {best.approach_id}: {best.summary}{risk_summary}"

    def _detect_seam(self, inputs: _ReasonInputs) -> Seam:
        if inputs.promotion_context is not None:
            return Seam.LEARNING
        if inputs.failure_context is not None:
            return Seam.REFLECTION
        return Seam.PLANNER

    # ------------------------------------------------------------------ #
    # Journaling                                                          #
    # ------------------------------------------------------------------ #

    def reasoning_history(self) -> list[dict[str, Any]]:
        return list(self._journal)

    def _journal_append(self, deliberation: Deliberation) -> None:
        self._journal.append({
            "seam": deliberation.seam.value,
            "subject": deliberation.subject,
            "confidence": deliberation.confidence,
            "recommendation": deliberation.recommendation.value,
            "recommended_approach": deliberation.recommended_approach,
            "depth_used": deliberation.depth_used,
            "hypotheses_used": deliberation.hypotheses_used,
            "abstained": deliberation.abstained,
            "reason": deliberation.reason,
            "model_used": self._model is not None,
            "timestamp": time.time(),
        })


def _subject_of(ctx: Any) -> str:
    if ctx is None:
        return "unknown"
    if hasattr(ctx, "task"):
        return ctx.task
    if hasattr(ctx, "subject"):
        return ctx.subject
    if hasattr(ctx, "task_id"):
        return ctx.task_id
    if hasattr(ctx, "name"):
        return ctx.name
    return str(ctx)
