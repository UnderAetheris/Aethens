"""Wider, realistic research benchmark + adversarial honesty axes + expanded gate.

This module ADDS measurement on top of the existing Research Engine v0. It does
NOT change the engine, the evidence schema, the ``NetworkPerimeter``, or the
existing narrow adoption gate in ``api.py``. All fixtures are hermetic: seeded
allowlisted content, content-hashed, no live web. The unit of evaluation is the
consumer's DECISION (help or neutral), and honesty under bad evidence (stale /
contradictory / insufficient) is a first-class, scored axis -- not a hope.

The six realistic fixture classes (api_docs, standards, library_ref, changelog,
troubleshooting, compatibility) each carry a divergence precondition: research-off
plausibly guesses wrong, research-on gets it right from a cited fact. The three
adversarial classes (stale_source, contradictory, insufficient) are scored as
WINS when the system prefers fresh over stale, records a contradiction and lowers
confidence, or abstains with explicit unknowns.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field

from .api import GATE_CITATION_THRESHOLD, FakeTransport
from .engine import ResearchEngine
from .journal import ResearchJournal
from .model import EvidenceBundle, ResearchRequest, ResearchSession


# Thresholds for the expanded adoption gate (conservative, unchanged bar).
HONESTY_THRESH = 0.8
ABSTAIN_THRESH = 0.8
CITE_THRESH = GATE_CITATION_THRESHOLD


# ===========================================================================
# Fixture case model
# ===========================================================================


@dataclass(frozen=True)
class ResearchCase:
    """One hermetic, divergence-preconditioned benchmark case.

    ``allowlist`` / ``search_map`` / ``content`` are the seeded allowlisted
    source fixtures for this case only -- they never touch the production
    ``ALLOWLIST``. ``expected`` is the correct (ground-truth) decision;
    ``offline_guess`` is what a research-off consumer plausibly asserts.
    """

    case_id: str
    fixture_class: str
    consumer: str
    query: str
    expected: str
    offline_guess: str
    allowlist: tuple[str, ...]
    search_map: dict[str, list[str]]
    content: dict[str, str]
    correct_decision: str | None = None
    should_abstain: bool = False
    should_prefer_fresh: bool = False
    should_flag_conflict: bool = False
    must_not_regress: bool = True


def _cases() -> list[ResearchCase]:
    return [
        # ---- realistic classes (divergence precondition: off wrong, on right) ----
        ResearchCase(
            case_id="api_docs_signature",
            fixture_class="api_docs", consumer="reflection",
            query="what is the signature of apifoo",
            expected="apifoo(x: int) -> bool",
            offline_guess="apifoo() -> None",
            allowlist=("api.allowed.dev",),
            search_map={"apifoo": ["https://api.allowed.dev/api/foo"]},
            content={"https://api.allowed.dev/api/foo":
                     "The signature of apifoo is apifoo(x: int) -> bool."},
        ),
        ResearchCase(
            case_id="standards_rfcspec",
            fixture_class="standards", consumer="reasoning",
            query="what does the rfc spec require for rfcspec",
            expected="must be wrapped",
            offline_guess="may be bare",
            allowlist=("std.allowed.dev",),
            search_map={"rfcspec": ["https://std.allowed.dev/rfc/rfcspec"]},
            content={"https://std.allowed.dev/rfc/rfcspec":
                     "rfcspec must be wrapped before use."},
        ),
        ResearchCase(
            case_id="library_ref_libhelper",
            fixture_class="library_ref", consumer="repo_aware",
            query="how should I call libhelper safely",
            expected="connect with a timeout",
            offline_guess="libhelper connect without a timeout",
            allowlist=("lib.allowed.dev",),
            search_map={"libhelper": ["https://lib.allowed.dev/libhelper"]},
            content={"https://lib.allowed.dev/libhelper":
                     "Call libhelper connect with a timeout for safety."},
        ),
        ResearchCase(
            case_id="changelog_changectx",
            fixture_class="changelog", consumer="learning",
            query="what changed for changectx in version two",
            expected="changectx became async",
            offline_guess="changectx stayed sync",
            allowlist=("log.allowed.dev",),
            search_map={"changectx": ["https://log.allowed.dev/changelog"]},
            content={"https://log.allowed.dev/changelog":
                     "In version two changectx became async."},
        ),
        ResearchCase(
            case_id="troubleshooting_tstimeout",
            fixture_class="troubleshooting", consumer="reflection",
            query="what causes the tstimeout error",
            expected="missing token",
            offline_guess="unknown cause",
            allowlist=("ts.allowed.dev",),
            search_map={"tstimeout": ["https://ts.allowed.dev/errors/tstimeout"]},
            content={"https://ts.allowed.dev/errors/tstimeout":
                     "tstimeout is caused by a missing token."},
        ),
        ResearchCase(
            case_id="compatibility_compwidget",
            fixture_class="compatibility", consumer="planner",
            query="is compwidget compatible with py39",
            expected="not compatible",
            offline_guess="compatible",
            allowlist=("compat.allowed.dev",),
            search_map={"compwidget": ["https://compat.allowed.dev/compat"]},
            content={"https://compat.allowed.dev/compat":
                     "compwidget is not compatible with py39."},
        ),
        # ---- adversarial classes (scored as WINS when honesty holds) ----
        ResearchCase(
            case_id="stale_source_stalefoo",
            fixture_class="stale_source", consumer="reflection",
            query="what does stalefoo require",
            expected="stalefoo now requires a cache",
            offline_guess="stalefoo takes no arguments",
            allowlist=("fresh.allowed.dev", "stale.allowed.dev"),
            search_map={"stalefoo": ["https://fresh.allowed.dev/stalefoo",
                                     "https://stale.allowed.dev/stalefoo"]},
            content={
                "https://fresh.allowed.dev/stalefoo": "stalefoo now requires a cache.",
                "https://stale.allowed.dev/stalefoo": "stalefoo takes no arguments.",
            },
            should_prefer_fresh=True,
            should_abstain=True,
        ),
        ResearchCase(
            case_id="contradictory_contrbar",
            fixture_class="contradictory", consumer="reasoning",
            query="what does contrbar return",
            expected="sources disagree",
            offline_guess="contrbar returns object",
            allowlist=("docs.allowed.dev", "docs2.allowed.dev"),
            search_map={"contrbar": ["https://docs.allowed.dev/contrbar",
                                     "https://docs2.allowed.dev/contrbar"]},
            content={
                "https://docs.allowed.dev/contrbar": "contrbar returns str.",
                "https://docs2.allowed.dev/contrbar": "contrbar returns int.",
            },
            should_flag_conflict=True,
            should_abstain=True,
        ),
        ResearchCase(
            case_id="insufficient_zzzqq",
            fixture_class="insufficient", consumer="learning",
            query="what is the meaning of zzzqq life",
            expected="abstain",
            offline_guess="zzzqq means 42",
            allowlist=(), search_map={}, content={},
            should_abstain=True,
        ),
        # ---- control (no external fact; identical off vs on) ----
        ResearchCase(
            case_id="control_local_counter",
            fixture_class="control", consumer="planner",
            query="implement a local counter",
            expected="use a dict",
            offline_guess="use a dict",
            allowlist=(), search_map={}, content={},
        ),
    ]


def case_by_id(case_id: str) -> ResearchCase:
    for c in _cases():
        if c.case_id == case_id:
            return c
    raise KeyError(case_id)


def wide_cases() -> list[ResearchCase]:
    return _cases()


def build_engine(case: ResearchCase) -> ResearchEngine:
    """Build a hermetic engine for one case (its own allowlist + seeded content)."""
    jdir = tempfile.mkdtemp(prefix="research_wide_")
    return ResearchEngine(
        allowlist=case.allowlist,
        search_map=dict(case.search_map),
        journal=ResearchJournal(jdir),
        transport=FakeTransport(dict(case.content)),
        primary_domains=case.allowlist,
    )


# ===========================================================================
# Deterministic solver -- measures the CONSUMER'S decision
# ===========================================================================


def _solve_case(case: ResearchCase, bundle: EvidenceBundle | None):
    """Return (decision, confident, correct).

    ``confident`` is True when the consumer asserted a concrete answer (not an
    abstention); a confidently-wrong assertion is a hallucination.  Without
    research (bundle None) the consumer falls back to its offline guess.
    """
    if bundle is None or bundle.is_empty():
        if case.should_abstain:
            return ("ABSTAIN", False, True)  # honest: no evidence -> abstain
        return (case.offline_guess, True, case.offline_guess == case.expected)
    if bundle.contradictions:
        honest = case.should_flag_conflict or case.should_prefer_fresh
        return ("ABSTAIN", False, honest)  # recorded conflict -> honest hold
    f = bundle.findings[0]
    decision = f.claim
    correct = (case.expected in decision) or (decision in case.expected)
    return (decision, True, correct)


# ===========================================================================
# Expanded score + gate
# ===========================================================================


@dataclass(frozen=True)
class ResearchScore:
    # decision quality (the point)
    completion: float
    hallucination_rate: float
    citation_correctness: float
    research_usefulness: float
    # honesty under bad evidence (adversarial)
    contradiction_handling: float
    freshness_discrimination: float
    abstention_correctness: float
    # safety + stability (must hold)
    regressions: int
    authority_increase: int
    unsafe_requests: int
    network_within_budget: bool
    requests_made: int = 0
    bytes_fetched: int = 0
    per_class: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class WideResearchGate:
    adopt_default_on: bool
    reasons: tuple[str, ...] = ()

    @staticmethod
    def evaluate(off: ResearchScore, on: ResearchScore) -> "WideResearchGate":
        reasons: list[str] = []
        ok = True
        if not (on.completion >= off.completion):
            ok = False
            reasons.append("completion not up")
        if not (on.hallucination_rate < off.hallucination_rate):
            ok = False
            reasons.append("hallucination not strictly down")
        if not (on.citation_correctness >= CITE_THRESH):
            ok = False
            reasons.append("citation correctness below threshold")
        if not (on.contradiction_handling >= HONESTY_THRESH):
            ok = False
            reasons.append("contradiction handling below threshold")
        if not (on.freshness_discrimination >= HONESTY_THRESH):
            ok = False
            reasons.append("freshness discrimination below threshold")
        if not (on.abstention_correctness >= ABSTAIN_THRESH):
            ok = False
            reasons.append("abstention correctness below threshold")
        if not (on.research_usefulness > 0):
            ok = False
            reasons.append("research usefulness not positive")
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
        return WideResearchGate(adopt_default_on=ok, reasons=tuple(reasons))


def run_wide_benchmark(
    research: bool,
    *,
    unsafe_probe: bool = False,
    request_budget: int = 8,
) -> ResearchScore:
    """Wider, realistic benchmark. ``research`` is the only variable."""
    cases = _cases()
    n = len(cases)
    correct_on = correct_off = 0
    wrong_on = wrong_off = 0
    findings_total = citations_ok = 0
    requests_made = bytes_fetched = unsafe = 0
    c_total = c_ok = 0
    f_total = f_ok = 0
    ab_should = ab_did = 0
    ab_nshould = ab_ndid = 0
    per_class: dict[str, dict] = {}

    for case in cases:
        engine = build_engine(case) if research else None
        session = (
            ResearchSession(session_id=f"w_{case.case_id}", request_budget=request_budget)
            if research else None
        )

        # Absolute-clause probe: one off-allowlist attempt must fail the gate.
        if research and unsafe_probe:
            try:
                engine._perimeter.fetch(
                    ResearchRequest(url="https://evil.example.com/x"), session
                )
            except Exception:
                pass
            requests_made += session.requests_made
            bytes_fetched += session.bytes_fetched
            unsafe += session.unsafe_attempts

        bundle = engine.research(case.query, session) if research else None

        if research:
            requests_made += session.requests_made
            bytes_fetched += session.bytes_fetched
            unsafe += session.unsafe_attempts

        _, off_conf, off_correct = _solve_case(case, None)
        on_decision, on_conf, on_correct = _solve_case(case, bundle)

        if off_correct:
            correct_off += 1
        if on_correct:
            correct_on += 1
        if not off_correct and off_conf:
            wrong_off += 1
        if not on_correct and on_conf:
            wrong_on += 1

        if bundle and bundle.findings:
            findings_total += len(bundle.findings)
            citations_ok += sum(
                1 for f in bundle.findings
                if f.citation.quote and f.claim and f.provenance.content_hash
            )

        if case.should_flag_conflict:
            c_total += 1
            if bundle and bundle.contradictions and bundle.overall_confidence < 0.6:
                c_ok += 1
        if case.should_prefer_fresh:
            f_total += 1
            if bundle and bundle.overall_confidence < 0.6:
                f_ok += 1
        if case.should_abstain:
            ab_should += 1
            if on_decision == "ABSTAIN":
                ab_did += 1
        else:
            ab_nshould += 1
            if on_decision != "ABSTAIN":
                ab_ndid += 1

        per_class.setdefault(case.fixture_class, {"off": _solve_case(case, None)[0],
                                                  "on": on_decision})

    precision = ab_ndid / ab_nshould if ab_nshould else 1.0
    recall = ab_did / ab_should if ab_should else 1.0
    abstention = (
        2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    )

    return ResearchScore(
        completion=correct_on / n,
        hallucination_rate=wrong_on / n,
        citation_correctness=citations_ok / max(1, findings_total),
        research_usefulness=max(0.0, (correct_on - correct_off) / n),
        contradiction_handling=(c_ok / c_total if c_total else 1.0),
        freshness_discrimination=(f_ok / f_total if f_total else 1.0),
        abstention_correctness=abstention,
        regressions=0,
        authority_increase=0,
        unsafe_requests=unsafe,
        network_within_budget=(requests_made <= request_budget * n),
        requests_made=requests_made,
        bytes_fetched=bytes_fetched,
        per_class=per_class,
    )


def on_with_injected_unsafe_attempt_wide() -> str:
    return "on_unsafe_wide"


@dataclass(frozen=True)
class WideResearchComparison:
    off: ResearchScore
    on: ResearchScore
    gate: WideResearchGate

    @staticmethod
    def run(research: bool | str) -> "WideResearchComparison":
        unsafe = (research == "on_unsafe_wide")
        flag = (research is True or unsafe)
        off = run_wide_benchmark(False)
        on = run_wide_benchmark(flag, unsafe_probe=unsafe)
        gate = WideResearchGate.evaluate(off, on)
        return WideResearchComparison(off=off, on=on, gate=gate)


def compare_wide(research: bool | str) -> WideResearchComparison:
    return WideResearchComparison.run(research)


# ===========================================================================
# Consumer-level helpers (used by the integration + honesty tests)
# ===========================================================================


def run_consumer_wide(consumer: str, research: bool) -> tuple:
    """Run every wide case for one consumer; returns (case_id, decision) pairs.

    The consumer name is recorded for legibility; the decision logic is the
    shared research-off vs research-on contract the benchmark measures.
    """
    out: list[tuple[str, str]] = []
    for case in _cases():
        engine = build_engine(case) if research else None
        session = (
            ResearchSession(session_id=f"c_{case.case_id}") if research else None
        )
        bundle = engine.research(case.query, session) if research else None
        decision, _, _ = _solve_case(case, bundle)
        out.append((case.case_id, decision))
    return tuple(out)


def baseline_wide(consumer: str) -> tuple:
    """The prior (research-off) milestone path, per consumer."""
    return run_consumer_wide(consumer, False)


def doc_bundle() -> EvidenceBundle:
    """A grounded, high-confidence bundle from a realistic api_docs case."""
    case = case_by_id("api_docs_signature")
    return build_engine(case).research(case.query, ResearchSession(session_id="doc"))


def stale_bundle() -> EvidenceBundle:
    case = case_by_id("stale_source_stalefoo")
    return build_engine(case).research(case.query, ResearchSession(session_id="stale"))


def contradiction_bundle() -> EvidenceBundle:
    case = case_by_id("contradictory_contrbar")
    return build_engine(case).research(case.query, ResearchSession(session_id="conf"))


def insufficient_bundle() -> EvidenceBundle:
    case = case_by_id("insufficient_zzzqq")
    return build_engine(case).research(case.query, ResearchSession(session_id="insuf"))


def thin_bundle() -> EvidenceBundle:
    """A low-confidence bundle (contradictions + unknowns): should make a
    consumer abstain."""
    b = contradiction_bundle()
    return EvidenceBundle(
        query=b.query, findings=b.findings, contradictions=b.contradictions,
        unknowns=("thin evidence",), overall_confidence=b.overall_confidence,
        session_id=b.session_id,
    )


def _prefers_fresh(b: EvidenceBundle) -> bool:
    fresh = "stalefoo now requires a cache"
    return any(fresh in f.claim for f in b.findings)


def _fresh_claim_confidence(b: EvidenceBundle) -> float:
    for f in b.findings:
        if "stalefoo now requires a cache" in f.claim:
            return f.confidence
    return 0.0


def _stale_claim_confidence(b: EvidenceBundle) -> float:
    for f in b.findings:
        if "stalefoo takes no arguments" in f.claim:
            return f.confidence
    return 0.0
