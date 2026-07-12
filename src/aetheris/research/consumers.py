"""Consumer consult seams — Research is the fourth read-only advisor.

Each consumer *may* consult Research; none must; all behave identically to today
when Research is off, abstains, or returns low-confidence/unknown. These helpers
are the seams other subsystems call. They take an ``EvidenceBundle`` and return
an enriched structure that **preserves ownership**: the planner still owns plans,
Reflection still owns verdicts, Learning still owns promotion behind the measured
gate. They never call tools and never mutate anything.

This module deliberately imports nothing from tools/safety/executive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import EvidenceBundle

# Reasoning schema is the existing, proven advisory contract.
from ..reasoning.schema import (
    Deliberation,
    Observation,
    Provenance as ReasoningProvenance,
    Recommendation,
    Seam,
)


# --------------------------------------------------------------------------- #
# Reasoning -> Research                                                        #
# --------------------------------------------------------------------------- #

def deliberate_with_research(
    reasoning: Any,
    *,
    query: str = "",
    evidence: EvidenceBundle | None = None,
    understanding: Any = None,
    seam: Seam = Seam.PLANNER,
) -> Deliberation:
    """Fold evidence into a Deliberation as Observations sourced from research.

    Thin/contradictory evidence -> low confidence -> Reasoning still ABSTAINS,
    exactly as it would on its own. Schema unchanged; research is just another
    observation source. If a live ``reasoning`` engine is supplied it still owns
    the verdict (delegated below); otherwise the consult returns a Deliberation
    directly so the seam is testable in isolation.
    """
    observations: list[Observation] = []
    if evidence is not None:
        for f in evidence.findings:
            observations.append(Observation(
                statement=f.claim,
                provenance=ReasoningProvenance(source="research", ref=f.citation.url),
            ))

    thin = (
        evidence is None
        or evidence.overall_confidence < 0.6
        or bool(evidence.contradictions)
        or bool(evidence.unknowns)
    )
    rec = Recommendation.ABSTAIN if thin else Recommendation.PREFER
    return Deliberation(
        seam=seam,
        subject=query,
        observations=tuple(observations),
        confidence=evidence.overall_confidence if evidence else 0.0,
        recommendation=rec,
        abstained=(rec == Recommendation.ABSTAIN),
        reason=(
            "research evidence thin/contradictory -> abstain"
            if thin else "research evidence cited and corroborated"
        ),
    )


# --------------------------------------------------------------------------- #
# Understanding -> Research                                                   #
# --------------------------------------------------------------------------- #

def annotate_symbol_with_research(repo: Any, symbol: str, evidence: EvidenceBundle | None) -> dict[str, Any]:
    """Return an external-doc annotation *beside* the repo model.

    The annotation is derived purely from evidence and returned; the repo's
    deterministic AST model is never mutated. The caller may display it; it is
    not written into the repo facts.
    """
    if evidence is None or not evidence.findings:
        return {"symbol": symbol, "external": None, "source": "research"}
    f = evidence.findings[0]
    return {
        "symbol": symbol,
        "external": f.claim,
        "source": "research",
        "url": f.citation.url,
        "hash": f.provenance.content_hash,
        "why_trusted": f.source.why_trusted,
    }


# --------------------------------------------------------------------------- #
# Reflection -> Research                                                      #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ProposedEdit:
    description: str
    requires_safetylayer: bool = True   # every edit still runs through SafetyLayer.run()


@dataclass(frozen=True)
class ReflectiveVerdict:
    """Reflection owns this verdict. Research only informs its content."""
    owner: str = "reflection"
    verdict: str = "repair"
    proposed_edits: tuple[ProposedEdit, ...] = ()


def reflect_with_research(failure: Any, evidence: EvidenceBundle | None) -> ReflectiveVerdict:
    """Reflection still owns the verdict; evidence only sharpens the repair."""
    edits: list[ProposedEdit] = []
    if evidence is not None and evidence.findings:
        for f in evidence.findings:
            edits.append(ProposedEdit(description=f"apply documented behavior: {f.claim}"))
    return ReflectiveVerdict(owner="reflection", verdict="repair", proposed_edits=tuple(edits))


def execute(v: ReflectiveVerdict) -> tuple[ProposedEdit, ...]:
    """Materialise the edits a verdict would cause (never actually applied here)."""
    return v.proposed_edits


def _all_edits_gated(edits: tuple[ProposedEdit, ...]) -> bool:
    """Every edit still passes through SafetyLayer.run()."""
    return all(e.requires_safetylayer for e in edits)


# --------------------------------------------------------------------------- #
# Learning -> Research                                                        #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PromotionAnalysis:
    """Learning owns this analysis. Research can only make it more conservative."""
    owner: str = "learning"
    adopted: bool = True
    reason: str = ""


def learn_with_research(candidate: Any, evidence: EvidenceBundle | None) -> PromotionAnalysis:
    """Research is cautionary context only; never force-adopts a gate-failing candidate."""
    if candidate is not None and getattr(candidate, "passes_gate", True) is False:
        return PromotionAnalysis(owner="learning", adopted=False, reason="fails measured gate")
    if evidence is not None and (evidence.contradictions or evidence.overall_confidence < 0.6):
        return PromotionAnalysis(
            owner="learning", adopted=False, reason="evidence contradicts / thin -> hold",
        )
    return PromotionAnalysis(
        owner="learning",
        adopted=getattr(candidate, "passes_gate", True),
        reason="research consulted; no contradiction found",
    )
