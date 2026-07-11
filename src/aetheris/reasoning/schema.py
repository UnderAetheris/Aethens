"""Reasoning schema: immutable advisory dataclasses.

The ONLY output of the reasoning engine is a Deliberation.  There is no
field that is a step, tool name, file path to write, or plan mutation.
The schema cannot express an action.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Recommendation(str, Enum):
    PREFER = "prefer"
    CAUTION = "caution"
    GATHER_CONTEXT = "gather_context"
    ABSTAIN = "abstain"


class Seam(str, Enum):
    PLANNER = "planner"
    REFLECTION = "reflection"
    LEARNING = "learning"


@dataclass(frozen=True)
class Provenance:
    """Every observation/risk traces to a source; no free-floating claims."""
    source: str      # "understanding" | "reflection" | "history" | "skills" | "memory" | "model"
    ref: str         # e.g. symbol name, file+line, task id, benchmark id


@dataclass(frozen=True)
class Observation:
    statement: str
    provenance: Provenance


@dataclass(frozen=True)
class Assumption:
    statement: str
    load_bearing: bool = False


@dataclass(frozen=True)
class Uncertainty:
    question: str
    resolvable_by: str = ""


@dataclass(frozen=True)
class Consequence:
    approach_id: str
    predicted: str
    expected_effect: str  # "retries_down" | "repairs_down" | "no_change" | "risk_dependents" | ...


@dataclass(frozen=True)
class Risk:
    approach_id: str
    statement: str
    severity: str        # "low" | "medium" | "high"
    provenance: Provenance


@dataclass(frozen=True)
class CandidateApproach:
    approach_id: str
    summary: str
    supports: tuple[str, ...] = ()
    score: float = 0.0


@dataclass(frozen=True)
class Deliberation:
    """The ONLY output of the reasoning engine. Pure data. Never a command."""
    seam: Seam
    subject: str
    assumptions: tuple[Assumption, ...] = ()
    observations: tuple[Observation, ...] = ()
    uncertainties: tuple[Uncertainty, ...] = ()
    candidates: tuple[CandidateApproach, ...] = ()
    risks: tuple[Risk, ...] = ()
    consequences: tuple[Consequence, ...] = ()
    confidence: float = 0.0
    recommendation: Recommendation = Recommendation.ABSTAIN
    recommended_approach: str | None = None
    depth_used: int = 0
    hypotheses_used: int = 0
    abstained: bool = True
    reason: str = ""
