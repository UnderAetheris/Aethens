"""Research Engine v0 — immutable evidence model.

The ONLY output of the Research Engine is an ``EvidenceBundle`` (and the
``ResearchFinding`` objects inside it). Every type here is ``frozen`` data:
none of them has a field that expresses an action, a step, a tool, a command,
a plan mutation, or an edit. This is the same type-level guarantee that
``Deliberation`` (reasoning) and ``Lesson`` (experience) already carry — the
schema *cannot* express an action, so there is no code path from evidence to
an effect.

The network request/session types are also defined here. A ``ResearchSession``
is the only thing that carries mutable egress counters (requests made, bytes
fetched, unsafe attempts); it is task-scoped and never persists.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlparse


class DomainTrust(str, Enum):
    ALLOWLISTED_PRIMARY = "allowlisted_primary"     # official docs, on the allowlist
    ALLOWLISTED_SECONDARY = "allowlisted_secondary"
    # nothing else is fetchable in v0; non-allowlisted domains never produce evidence


class PerimeterDenied(Exception):
    """A request was stopped by the NetworkPerimeter (deny-wins)."""


class BudgetExceeded(Exception):
    """A task session exhausted one of its egress budgets."""


class ResearchError(Exception):
    """Any other research failure (never an egress success)."""


@dataclass(frozen=True)
class Provenance:
    domain: str
    url: str                     # HTTPS, allowlisted, redirect-bounded
    fetched_at: float
    from_cache: bool
    content_hash: str            # sha256 of the fetched, size-bounded content
    perimeter_decision: str      # "allowed" | "dry_run" | why-allowed record


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    quote: str                   # the exact extracted span backing the finding
    locator: str                 # anchor / section / line, best-effort


@dataclass(frozen=True)
class Source:
    domain: str
    trust: DomainTrust
    why_trusted: str             # explicit reason (on allowlist as official docs, etc.)


@dataclass(frozen=True)
class ResearchFinding:
    """One extracted, cited claim. DATA. No method acts. No execution field."""
    claim: str
    source: Source
    citation: Citation
    provenance: Provenance
    confidence: float = 0.0      # 0-1, deterministic from trust/corroboration/freshness
    freshness: float = 0.0       # recency signal


@dataclass(frozen=True)
class EvidenceBundle:
    """The ONLY output of the Research Engine. Immutable. Terminal. Never executes."""
    query: str
    findings: tuple[ResearchFinding, ...] = ()
    contradictions: tuple[str, ...] = ()   # where sources disagree
    unknowns: tuple[str, ...] = ()         # what the evidence could NOT establish
    overall_confidence: float = 0.0        # low when thin/conflicting -> honest
    session_id: str = ""                   # task-scoped
    # bookkeeping for journaling / explainability
    requests_made: int = 0
    bytes_fetched: int = 0
    dry_run: bool = False

    def is_empty(self) -> bool:
        return len(self.findings) == 0


@dataclass(frozen=True)
class ResearchQuery:
    """A normalized research question, scoped to a session."""
    raw: str
    normalized: str = ""

    def __post_init__(self) -> None:
        if not self.normalized:
            object.__setattr__(self, "normalized", self.raw.strip().lower())


@dataclass(frozen=True)
class ResearchRequest:
    """A single egress request. GET-only, no auth, no cookies, no JS by contract."""
    url: str
    # Test/transport affordances (all optional):
    disallowed_by_robots: bool = False
    # Pre-declared content traits an injected transport can echo into the
    # response so MIME/size validation runs against a real RawResponse.
    declared_mime: str | None = None
    declared_size: int | None = None

    @property
    def domain(self) -> str:
        return urlparse(self.url).netloc or self.url

    @property
    def scheme(self) -> str:
        return urlparse(self.url).scheme


@dataclass
class ResearchSession:
    """Task-scoped egress budget holder. The only mutable research state.

    No request may leave the machine outside an explicit session, and every
    counter here is closed when the task ends. There is no persistent crawl
    identity, no cookie jar, no background thread.
    """
    session_id: str
    dry_run: bool = False
    request_budget: int = 8
    timeout_s: float = 10.0
    size_budget: int = 256 * 1024        # 256 KiB hard cap per response
    rate_budget: int = 16                 # requests per window
    rate_window_s: float = 60.0
    # mutable counters (closed with the task)
    requests_made: int = 0
    bytes_fetched: int = 0
    unsafe_attempts: int = 0
    _request_times: list[float] = field(default_factory=list, repr=False)

    @property
    def still_open(self) -> bool:
        return self.requests_made < self.request_budget


@dataclass(frozen=True)
class RawResponse:
    """An immutable record of one egress outcome. Never executed; just data."""
    url: str
    final_url: str
    status: int
    content_type: str
    content: bytes
    redirect_count: int = 0
    from_cache: bool = False
    # Structural guarantees: the perimeter only ever builds plain GETs.
    auth_sent: bool = False
    cookies_sent: bool = False
    js_executed: bool = False


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _now() -> float:
    return time.time()


def bundle_from_parts(
    query: str,
    findings: tuple[ResearchFinding, ...],
    contradictions: tuple[str, ...],
    unknowns: tuple[str, ...],
    session: ResearchSession,
    dry_run: bool = False,
) -> EvidenceBundle:
    """Assemble a bundle with honesty-correct overall confidence."""
    if findings:
        conf = sum(f.confidence for f in findings) / len(findings)
        if contradictions:
            # Contradictory sources => low confidence, honestly.
            conf = max(0.0, conf - 0.5 * len(contradictions))
    elif unknowns or contradictions:
        conf = 0.1
    else:
        conf = 0.0
    return EvidenceBundle(
        query=query,
        findings=findings,
        contradictions=contradictions,
        unknowns=unknowns,
        overall_confidence=round(min(1.0, conf), 4),
        session_id=session.session_id,
        requests_made=session.requests_made,
        bytes_fetched=session.bytes_fetched,
        dry_run=dry_run,
    )
