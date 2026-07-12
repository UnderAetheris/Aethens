"""Research Engine v0 — the fourth read-only advisor, pointed at the outside world.

Information increases; authority does not. The engine holds no tool, no
SafetyLayer (execution gate), no plan mutator, no memory/skill/config writer, no
executive. Its only outputs are frozen ``EvidenceBundle`` objects produced by a
one-directional pipeline that terminates in data. Every byte that leaves the
machine does so through the ``NetworkPerimeter``, the strongest gate in the
project. Default-off until the adoption gate clears.
"""
from __future__ import annotations

from .api import (
    ALLOWLIST,
    BenchmarkResult,
    FakeTransport,
    GATE_CITATION_THRESHOLD,
    ResearchComparison,
    ResearchGate,
    SEARCH_MAP,
    baseline_hierarchical_v0,
    compare,
    off,
    on,
    on_with_injected_unsafe_attempt,
    run_benchmark,
)
from .consumers import (
    annotate_symbol_with_research,
    deliberate_with_research,
    execute,
    learn_with_research,
    reflect_with_research,
    _all_edits_gated,
)
from .engine import ResearchEngine
from .journal import ResearchJournal
from .model import (
    BudgetExceeded,
    Citation,
    DomainTrust,
    EvidenceBundle,
    PerimeterDenied,
    Provenance,
    RawResponse,
    ResearchError,
    ResearchFinding,
    ResearchQuery,
    ResearchRequest,
    ResearchSession,
    Source,
    bundle_from_parts,
    content_hash,
)
from .perimeter import NetworkPerimeter

__all__ = [
    "ALLOWLIST",
    "BenchmarkResult",
    "FakeTransport",
    "GATE_CITATION_THRESHOLD",
    "ResearchComparison",
    "ResearchGate",
    "SEARCH_MAP",
    "baseline_hierarchical_v0",
    "compare",
    "off",
    "on",
    "on_with_injected_unsafe_attempt",
    "run_benchmark",
    "annotate_symbol_with_research",
    "deliberate_with_research",
    "execute",
    "learn_with_research",
    "reflect_with_research",
    "_all_edits_gated",
    "ResearchEngine",
    "ResearchJournal",
    "BudgetExceeded",
    "Citation",
    "DomainTrust",
    "EvidenceBundle",
    "PerimeterDenied",
    "Provenance",
    "RawResponse",
    "ResearchError",
    "ResearchFinding",
    "ResearchQuery",
    "ResearchRequest",
    "ResearchSession",
    "Source",
    "bundle_from_parts",
    "content_hash",
    "NetworkPerimeter",
]
