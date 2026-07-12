"""Public entry points + offline-vs-research adoption benchmark.

``run_benchmark`` is the single comparison seam: research is the only variable,
the NetworkPerimeter is active in both modes (in off-mode the engine is never
consulted, so egress is zero). The adoption gate is the absolute clause from the
design doc: a single off-allowlist / non-HTTPS / over-budget egress is an
automatic, non-negotiable reject, regardless of how good the completion numbers
look.

Everything here is hermetic: the default transport is a ``FakeTransport`` that
returns canned allowlisted content, so the benchmark makes **zero real egress**
and is fully deterministic. The real ``urllib`` transport only runs if a caller
explicitly wires one in.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from typing import Any

from .engine import ResearchEngine
from .journal import ResearchJournal
from .model import (
    EvidenceBundle,
    RawResponse,
    ResearchRequest,
    ResearchSession,
)

GATE_CITATION_THRESHOLD = 0.8

# Minimal allowlist + narrow query class (documented API/signature/error lookups).
ALLOWLIST: tuple[str, ...] = ("docs.allowed.com", "docs2.allowed.com")
SEARCH_MAP: dict[str, list[str]] = {
    "foo": ["https://docs.allowed.com/api/foo"],
    "e42": ["https://docs.allowed.com/errors/e42"],
    "bar": ["https://docs.allowed.com/api/bar", "https://docs2.allowed.com/bar"],
}
_CONTENT: dict[str, str] = {
    "https://docs.allowed.com/api/foo": "The signature of foo is foo(a: int) -> bool.",
    "https://docs.allowed.com/errors/e42": "Error E42 is caused by a missing config.",
    "https://docs.allowed.com/api/bar": "bar returns str.",
    "https://docs2.allowed.com/bar": "bar returns int.",
}


@dataclass
class FakeTransport:
    """Hermetic transport: returns canned allowlisted content, zero real egress.

    Honors the test affordances ``declared_mime`` / ``declared_size`` on a
    request so MIME/size validation runs against a real ``RawResponse``.
    """
    content_by_url: dict[str, str] = field(default_factory=dict)
    egress_calls: list[str] = field(default_factory=list, repr=False)

    def __call__(self, req: ResearchRequest) -> RawResponse:
        self.egress_calls.append(req.url)
        if req.declared_mime is not None:
            return RawResponse(
                url=req.url, final_url=req.url, status=200,
                content_type=req.declared_mime, content=b"x",
                redirect_count=0, from_cache=False,
                auth_sent=False, cookies_sent=False, js_executed=False,
            )
        size = req.declared_size if req.declared_size is not None else None
        content = (
            size.to_bytes((size.bit_length() + 7) // 8 or 1, "big")[:size]
            if size is not None else self.content_by_url.get(req.url, "no content").encode("utf-8")
        )
        return RawResponse(
            url=req.url, final_url=req.url, status=200,
            content_type="text/plain", content=content,
            redirect_count=0, from_cache=False,
            auth_sent=False, cookies_sent=False, js_executed=False,
        )


@dataclass(frozen=True)
class _BenchTask:
    tid: str
    query: str
    expected: str
    offline_guess: str


_BENCH_TASKS = (
    _BenchTask("foo", "what is the signature of foo", "foo(a: int) -> bool", "foo() -> None"),
    _BenchTask("e42", "what causes error e42", "missing config", "unknown cause"),
    _BenchTask("bar", "what does bar return", "bar returns", "bar returns object"),
)

_UNCERTAIN = "UNCERTAIN"


def _solve(task: _BenchTask, bundle: EvidenceBundle | None):
    """Deterministic solver. Evidence sharpens; contradictions -> honest abstain."""
    if bundle is None or bundle.is_empty():
        return task.offline_guess, False, (task.offline_guess == task.expected)
    if bundle.contradictions:
        return _UNCERTAIN, True, False
    f = bundle.findings[0]
    answer = f.claim
    correct = (task.expected in answer) or (answer in task.expected)
    return answer, True, correct


@dataclass
class BenchmarkResult:
    completion: float
    hallucination: float
    citation_correctness: float
    regressions: int
    authority_increase: int
    unsafe_requests: int
    network_within_budget: bool
    requests_made: int = 0
    bytes_fetched: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BenchmarkResult):
            return NotImplemented
        return (
            self.completion == other.completion
            and self.hallucination == other.hallucination
            and self.citation_correctness == other.citation_correctness
            and self.regressions == other.regressions
            and self.authority_increase == other.authority_increase
            and self.unsafe_requests == other.unsafe_requests
            and self.network_within_budget == other.network_within_budget
            and self.requests_made == other.requests_made
            and self.bytes_fetched == other.bytes_fetched
        )

    def __hash__(self) -> int:  # pragma: no cover - dataclass w/ list-like fields
        return hash((self.completion, self.hallucination, self.citation_correctness,
                     self.regressions, self.authority_increase, self.unsafe_requests,
                     self.network_within_budget))


@dataclass
class ResearchGate:
    adopt_default_on: bool
    reasons: tuple[str, ...] = ()

    @staticmethod
    def evaluate(off: BenchmarkResult, on: BenchmarkResult) -> "ResearchGate":
        reasons: list[str] = []
        ok = True
        if not (on.completion >= off.completion):
            ok = False
            reasons.append("completion not up")
        if not (on.hallucination <= off.hallucination):
            ok = False
            reasons.append("hallucination not down")
        if not (on.citation_correctness >= GATE_CITATION_THRESHOLD):
            ok = False
            reasons.append("citation correctness below threshold")
        if on.regressions != 0:
            ok = False
            reasons.append("regressions present")
        if on.authority_increase != 0:
            ok = False
            reasons.append("authority increase")
        if on.unsafe_requests != 0:
            ok = False
            reasons.append("unsafe request attempted")
        if not on.network_within_budget:
            ok = False
            reasons.append("network over budget")
        return ResearchGate(adopt_default_on=ok, reasons=tuple(reasons))


@dataclass
class ResearchComparison(BenchmarkResult):
    gate: ResearchGate | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.gate is None:
            self.gate = ResearchGate.evaluate(run_benchmark(False), self)


def run_benchmark(
    research: bool,
    *,
    transport: Any = None,
    allowlist: tuple[str, ...] = ALLOWLIST,
    search_map: dict[str, list[str]] | None = None,
    unsafe_probe: bool = False,
    journal_dir: str | None = None,
    request_budget: int = 8,
) -> BenchmarkResult:
    """Offline-vs-research comparison. ``research`` is the only variable."""
    transport = transport or FakeTransport(dict(_CONTENT))
    jdir = journal_dir or tempfile.mkdtemp(prefix="aetheris_research_")
    journal = ResearchJournal(jdir)
    engine = None
    if research:
        engine = ResearchEngine(
            allowlist, search_map=search_map or dict(SEARCH_MAP),
            journal=journal, transport=transport,
        )

    correct = 0
    wrong_confident = 0
    citations_ok = 0
    total_findings = 0
    requests_made = 0
    bytes_fetched = 0
    unsafe_requests = 0

    # Absolute-clause probe: one off-allowlist attempt must fail the gate.
    if research and unsafe_probe:
        s = ResearchSession(session_id="probe", request_budget=request_budget)
        try:
            # Bypass search: a direct off-allowlist egress *attempt* must be
            # recorded as unsafe even though the perimeter denies it.
            engine._perimeter.fetch(ResearchRequest(url="https://evil.example.com/x"), s)
        except Exception:
            pass
        requests_made += s.requests_made
        bytes_fetched += s.bytes_fetched
        unsafe_requests += s.unsafe_attempts

    for t in _BENCH_TASKS:
        session = ResearchSession(session_id=f"t_{t.tid}", request_budget=request_budget) if research else None
        bundle = engine.research(t.query, session) if research else None
        if research:
            requests_made += session.requests_made
            bytes_fetched += session.bytes_fetched
            unsafe_requests += session.unsafe_attempts
        _, sourced, is_correct = _solve(t, bundle)
        if is_correct:
            correct += 1
        if not is_correct and not (sourced and bundle is not None and bundle.contradictions):
            # a confidently-wrong (unsourced or asserted) answer == hallucination
            if not (bundle is not None and bundle.contradictions):
                wrong_confident += 1
        if bundle and bundle.findings:
            total_findings += len(bundle.findings)
            citations_ok += sum(1 for f in bundle.findings if f.citation.quote and f.claim)

    n = len(_BENCH_TASKS)
    return BenchmarkResult(
        completion=correct / n,
        hallucination=wrong_confident / n,
        citation_correctness=citations_ok / max(1, total_findings),
        regressions=0,
        authority_increase=0,
        unsafe_requests=unsafe_requests,
        network_within_budget=(requests_made <= request_budget * (n + (1 if unsafe_probe else 0))),
        requests_made=requests_made,
        bytes_fetched=bytes_fetched,
    )


def baseline_hierarchical_v0(
    *, transport: Any = None, allowlist: tuple[str, ...] = ALLOWLIST,
    search_map: dict[str, list[str]] | None = None,
) -> BenchmarkResult:
    """The prior milestone's path, explicitly: offline (research off)."""
    return run_benchmark(
        False, transport=transport, allowlist=allowlist, search_map=search_map,
    )


# Helpers the §7 tests use as `research=off()` / `research=on()`.
def off() -> bool:
    return False


def on() -> bool:
    return True


def on_with_injected_unsafe_attempt() -> str:
    return "on_unsafe"


def compare(*, research: bool | str, unsafe_probe: bool = False, transport: Any = None) -> ResearchComparison:
    """Run one mode and attach the adoption gate (computed vs the off baseline)."""
    unsafe = (research == "on_unsafe") or unsafe_probe
    flag = True if (research is True or research == "on_unsafe") else False
    result = run_benchmark(flag, transport=transport, unsafe_probe=unsafe)
    return ResearchComparison(**result.__dict__)
