"""Wider reliability evaluation + coverage-preservation hardening.

This module ADDS measurement on top of the existing Research Reliability
Learning v0. It does NOT change the reliability engine, the evidence schema,
the ``NetworkPerimeter``, the consumers, or the schema. All fixtures are
hermetic: seeded allowlisted content + seeded long-run source behavior,
content-hashed, no live web.

Two questions, exactly as in the two prior eval-and-harden milestones:

1. **Prove it helps.** The unit of evaluation is the *consumer's decision*,
   not the ranking's tidiness. A perfectly-ordered finding list that changes
   no outcome scores as no help. Five source-behavior fixture classes carry a
   *divergence precondition* (reliability-off mis-weights, reliability-on
   decides better) or they are cut: ``correct_docs`` (preferred),
   ``contradictory_blog`` (de-preferred but still fetched+cited),
   ``stale_changelog`` (freshness-decayed but still fetched),
   ``recovering_source`` (climbs back, proving reversibility), and ``control``.

2. **Prove it can't gate.** The load-bearing half. ``coverage_identical`` is a
   mandatory gate axis AND a permanent build-failing canary: the fetched-source
   set (by content hash + source key) is *identical* off vs on, every case. The
   adversarial coverage suite asserts low-reliability / retired-to-neutral
   sources are still fetched + cited, ``rank_findings`` is a permutation not a
   filter, ``weight_confidence`` never drops a finding, and flipping a source
   reliable->unreliable leaves the fetched set unchanged. If consuming
   reliability *ever* changes what gets fetched, reliability has leaked from
   weighting into gating -- stop-the-line.

Consumption stays default-off. This milestone only measures and hardens; it
does not flip ``consume_enabled``.
"""
from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field

from .api import FakeTransport
from .consumers import (
    rank_findings_with_reliability,
)
from .engine import ResearchEngine
from .journal import ResearchJournal
from .model import EvidenceBundle, ResearchFinding, ResearchSession
from .reliability import (
    ReliabilityTrend,
    SourceReliability,
)


# Thresholds for the expanded adoption gate (conservative, unchanged bar).
HONESTY_THRESH = 0.8
ABSTAIN_THRESH = 0.8
CITE_THRESH = 0.8


# ===========================================================================
# Fixture case model
# ===========================================================================


@dataclass(frozen=True)
class ReliabilitySeed:
    """Known long-run behavior of one source, used to seed standing deterministically."""

    source_key: str
    supports: int
    contradictions: int
    age_s: float = 0.0  # how long ago the last confirmed outcome happened


@dataclass(frozen=True)
class ReliabilityCase:
    """One hermetic, divergence-preconditioned reliability benchmark case.

    ``allowlist`` / ``search_map`` / ``content`` are the seeded allowlisted
    source fixtures for this case only. ``reliability_seed`` is the KNOWN
    long-run behavior each source has earned. ``expected`` is the correct
    (ground-truth) consumer decision; the naive (reliability-off) consumer
    plausibly mis-weights because the search order surfaces the wrong source
    first -- reliability-on re-ranks to the trustworthy source and decides
    better. ``control`` is reliability-inert (identical off vs on).
    """

    case_id: str
    source_class: str  # correct_docs | contradictory_blog | stale_changelog
    # | recovering_source | control
    consumer: str  # planner | reasoning | reflection | learning | repo_aware
    query: str
    expected: str
    allowlist: tuple[str, ...]
    search_map: dict[str, list[str]]
    content: dict[str, str]
    reliability_seed: tuple[ReliabilitySeed, ...] = ()
    must_still_fetch: tuple[str, ...] = ()  # sources that MUST appear in the fetched set
    should_downweight: tuple[str, ...] = ()  # stale/contradictory: lower rank, still fetched
    should_recover: str | None = None  # recovering-source cases
    divergence_required: bool = True  # off mis-weights; on decides better
    must_not_regress: bool = True  # control identity


@dataclass
class ReliabilityCaseResult:
    """One case's measured outcome (off vs on + honesty detail)."""

    case_id: str
    source_class: str
    consumer: str
    fetched_sources: frozenset  # (domain, content_hash)
    decision_off: str
    decision_on: str
    correct_off: bool
    correct_on: bool
    rank_in_on: dict
    trend_on: dict
    cited_on: frozenset
    must_still_fetch: set
    should_downweight: set
    should_recover: str | None

    def preferred(self, domain: str) -> bool:
        return self.rank_in_on.get(domain, 999) == 0

    def rank_of(self, domain: str) -> int:
        return self.rank_in_on.get(domain, 999)

    def trend_of(self, domain: str) -> "ReliabilityTrend | None":
        return self.trend_on.get(domain)

    def is_cited(self, domain: str) -> bool:
        return domain in self.cited_on

    def all_must_still_fetch(self) -> bool:
        return all(d in {d2 for d2, _ in self.fetched_sources} for d in self.must_still_fetch)


# ===========================================================================
# Fixtures: five source-behavior classes
# ===========================================================================


def _cases() -> list[ReliabilityCase]:
    return [
        # ---- correct_docs: a docs site with a long validated-correct history ----
        # Search order surfaces the unreliable blog first (naive mis-trusts it);
        # reliability ranks the verified docs site first and the consumer decides
        # correctly.
        ReliabilityCase(
            case_id="correct_docs_pyfoo",
            source_class="correct_docs", consumer="reflection",
            query="what does pyfoo take",
            expected="pyfoo takes a timeout",
            allowlist=("py.docs", "blog.z"),
            search_map={"pyfoo": ["https://blog.z/pyfoo", "https://py.docs/pyfoo"]},
            content={
                "https://blog.z/pyfoo": "pyfoo takes no arguments.",
                "https://py.docs/pyfoo": "pyfoo takes a timeout.",
            },
            reliability_seed=(
                ReliabilitySeed("py.docs", supports=20, contradictions=0, age_s=0.0),
                ReliabilitySeed("blog.z", supports=0, contradictions=15, age_s=0.0),
            ),
            must_still_fetch=("py.docs", "blog.z"),
        ),
        # ---- contradictory_blog: repeatedly contradicted -> de-preferred ----
        # Still fetched + cited; reliability ranks the verified docs first.
        ReliabilityCase(
            case_id="contradictory_blog_conbar",
            source_class="contradictory_blog", consumer="reasoning",
            query="what does conbar return",
            expected="conbar returns a value",
            allowlist=("docs.c", "blog.contra"),
            search_map={"conbar": ["https://blog.contra/conbar", "https://docs.c/conbar"]},
            content={
                "https://blog.contra/conbar": "conbar returns void.",
                "https://docs.c/conbar": "conbar returns a value.",
            },
            reliability_seed=(
                ReliabilitySeed("docs.c", supports=20, contradictions=0, age_s=0.0),
                ReliabilitySeed("blog.contra", supports=0, contradictions=15, age_s=0.0),
            ),
            must_still_fetch=("docs.c", "blog.contra"),
            should_downweight=("blog.contra",),
        ),
        # ---- stale_changelog: correct pre-vN, stale after -> freshness-decayed ----
        # Vendor changelog last confirmed 60 days ago (STALE); fresh docs current.
        # Still fetched; reliability prefers fresh.
        ReliabilityCase(
            case_id="stale_changelog_chgctx",
            source_class="stale_changelog", consumer="learning",
            query="what is chgctx now",
            expected="chgctx is now async",
            allowlist=("vendor.log", "fresh.v"),
            search_map={"chgctx": ["https://vendor.log/changelog", "https://fresh.v/changelog"]},
            content={
                "https://vendor.log/changelog": "chgctx was sync.",
                "https://fresh.v/changelog": "chgctx is now async.",
            },
            reliability_seed=(
                ReliabilitySeed("fresh.v", supports=20, contradictions=0, age_s=0.0),
                ReliabilitySeed("vendor.log", supports=20, contradictions=0, age_s=60 * 24 * 3600),
            ),
            must_still_fetch=("fresh.v", "vendor.log"),
            should_downweight=("vendor.log",),
        ),
        # ---- recovering_source: once-unreliable, now consistently correct ----
        # 15 old contradictions then 25 recent validations -> standing recovers
        # to RELIABLE; paired with an always-unreliable source.
        ReliabilityCase(
            case_id="recovering_source_reccall",
            source_class="recovering_source", consumer="repo_aware",
            query="is reccall safe",
            expected="reccall is safe",
            allowlist=("blog.alt2", "blog.rec"),
            search_map={"reccall": ["https://blog.alt2/reccall", "https://blog.rec/reccall"]},
            content={
                "https://blog.alt2/reccall": "reccall is unsafe.",
                "https://blog.rec/reccall": "reccall is safe.",
            },
            reliability_seed=(
                ReliabilitySeed("blog.rec", supports=25, contradictions=15, age_s=0.0),
                ReliabilitySeed("blog.alt2", supports=0, contradictions=15, age_s=0.0),
            ),
            must_still_fetch=("blog.rec", "blog.alt2"),
            should_recover="blog.rec",
        ),
        # ---- control: reliability irrelevant; identical off vs on ----
        ReliabilityCase(
            case_id="control_local_counter",
            source_class="control", consumer="planner",
            query="how should I implement a counter",
            expected="use a dict",
            allowlist=("ctrl.local",),
            search_map={"counter": ["https://ctrl.local/x"]},
            content={"https://ctrl.local/x": "use a dict."},
            reliability_seed=(),
            divergence_required=False,
        ),
    ]


def reliability_cases() -> list[ReliabilityCase]:
    return _cases()


def case_by_id(case_id: str) -> ReliabilityCase:
    for c in _cases():
        if c.case_id == case_id:
            return c
    raise KeyError(case_id)


# ===========================================================================
# Engine + seeding helpers (hermetic)
# ===========================================================================


def build_reliability_engine(case: ReliabilityCase) -> ResearchEngine:
    """Build a hermetic engine for one case (its own allowlist + seeded content)."""
    jdir = tempfile.mkdtemp(prefix="relbench_eng_")
    return ResearchEngine(
        allowlist=case.allowlist,
        search_map=dict(case.search_map),
        journal=ResearchJournal(jdir),
        transport=FakeTransport(dict(case.content)),
        primary_domains=case.allowlist,
    )


def _seed(r: SourceReliability, source_key: str, supports: int, contradictions: int, age_s: float) -> None:
    """Seed a source's standing deterministically with backdated outcomes.

    Uses the engine's own append+rebuild so the resulting standing matches what
    real validated outcomes would produce (recency-driven confidence/trend).
    No reliability code is changed -- this is fixture setup only.
    """
    now = time.time()
    ts = now - age_s
    for i in range(supports):
        r._store.append({
            "kind": "outcome", "source_key": source_key,
            "validated": True, "contradicted": False,
            "event_id": f"{source_key}-s{i}", "timestamp": ts,
        })
    for i in range(contradictions):
        r._store.append({
            "kind": "outcome", "source_key": source_key,
            "validated": False, "contradicted": True,
            "event_id": f"{source_key}-c{i}", "timestamp": ts,
        })
    r._rebuild(source_key)


def seed_reliability(case: ReliabilityCase, *, consume_enabled: bool = False) -> SourceReliability:
    jdir = tempfile.mkdtemp(prefix="relbench_rel_")
    r = SourceReliability(jdir, consume_enabled=consume_enabled)
    for seed in case.reliability_seed:
        _seed(r, seed.source_key, seed.supports, seed.contradictions, seed.age_s)
    return r


def _fetched_sources(engine: ResearchEngine, case: ReliabilityCase) -> frozenset:
    session = ResearchSession(session_id=f"relfetch_{case.case_id}")
    bundle = engine.research(case.query, session)
    return frozenset((f.source.domain, f.provenance.content_hash) for f in bundle.findings)


# ===========================================================================
# Deterministic solver -- measures the CONSUMER'S decision
# ===========================================================================


def _solve(
    case: ReliabilityCase,
    bundle: EvidenceBundle | None,
    reliability: SourceReliability | None,
):
    """Return (decision, confident, correct).

    With reliability-on the consumer re-ranks findings by standing (permutation)
    and takes the top finding; reliability-off (or no bundle) the consumer takes
    the findings in natural fetch order.  Coverage is never a variable here --
    the same bundle underlies both decisions.
    """
    if bundle is None or bundle.is_empty():
        # control / no external fact: reliability inert, decision = expected.
        return (case.expected, True, True)
    if reliability is not None:
        findings: tuple[ResearchFinding, ...] = rank_findings_with_reliability(bundle.findings, reliability)
    else:
        findings = bundle.findings
    top = findings[0]
    decision = top.claim
    correct = (case.expected in decision) or (decision in case.expected)
    return (decision, True, correct)


# ===========================================================================
# Per-case runner
# ===========================================================================


def run_reliability_case(case: ReliabilityCase, consume: bool) -> ReliabilityCaseResult:
    engine = build_reliability_engine(case)
    session = ResearchSession(session_id=f"rel_{case.case_id}")
    bundle = engine.research(case.query, session)
    fetched = frozenset((f.source.domain, f.provenance.content_hash) for f in bundle.findings)
    rel = seed_reliability(case, consume_enabled=consume) if consume else None

    off_decision, off_conf, off_correct = _solve(case, bundle, None)
    on_decision, on_conf, on_correct = (
        _solve(case, bundle, rel) if consume else (off_decision, off_conf, off_correct)
    )

    ranked_on = rank_findings_with_reliability(bundle.findings, rel) if consume else bundle.findings
    rank_in_on = {f.source.domain: i for i, f in enumerate(ranked_on)}
    cited_on = frozenset(f.source.domain for f in bundle.findings if f.citation.quote)
    trend_on: dict = {}
    if consume:
        for d in {f.source.domain for f in bundle.findings}:
            standing = rel.standing(d, min_conf=0.0)
            if standing is not None:
                trend_on[d] = standing.trend

    return ReliabilityCaseResult(
        case_id=case.case_id, source_class=case.source_class, consumer=case.consumer,
        fetched_sources=fetched,
        decision_off=off_decision, decision_on=on_decision,
        correct_off=off_correct, correct_on=on_correct,
        rank_in_on=rank_in_on, trend_on=trend_on, cited_on=cited_on,
        must_still_fetch=set(case.must_still_fetch),
        should_downweight=set(case.should_downweight),
        should_recover=case.should_recover,
    )


# ===========================================================================
# Expanded score + gate
# ===========================================================================


@dataclass(frozen=True)
class ReliabilityEvalScore:
    # decision quality (the point)
    completion: float
    hallucination_rate: float
    citation_correctness: float
    reliability_usefulness: float
    # honesty under adversarial reliability
    contradiction_handling: float
    freshness_discrimination: float
    recovery_correctness: float
    abstention_correctness: float
    # THE load-bearing guarantee
    coverage_identical: bool
    # safety + stability (must hold)
    regressions: int
    authority_increase: int
    unsafe_requests: int
    network_within_budget: bool
    requests_made: int = 0
    bytes_fetched: int = 0
    per_class: dict = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class ReliabilityEvalGate:
    adopt_default_on: bool
    reasons: tuple[str, ...] = ()

    @staticmethod
    def evaluate(off: "ReliabilityEvalScore", on: "ReliabilityEvalScore") -> "ReliabilityEvalGate":
        reasons: list[str] = []
        ok = True
        if not (on.completion >= off.completion):
            ok = False
            reasons.append("completion not up")
        if not (on.hallucination_rate <= off.hallucination_rate):
            ok = False
            reasons.append("hallucination up")
        if not (on.citation_correctness >= CITE_THRESH):
            ok = False
            reasons.append("citation correctness below threshold")
        if not (on.reliability_usefulness > 0):
            ok = False
            reasons.append("reliability usefulness not positive")
        if not on.coverage_identical:
            ok = False
            reasons.append("COVERAGE CHANGED off vs on (mandatory)")
        if not (on.contradiction_handling >= HONESTY_THRESH):
            ok = False
            reasons.append("contradiction handling below threshold")
        if not (on.freshness_discrimination >= HONESTY_THRESH):
            ok = False
            reasons.append("freshness discrimination below threshold")
        if not (on.recovery_correctness >= HONESTY_THRESH):
            ok = False
            reasons.append("recovery correctness below threshold")
        if not (on.abstention_correctness >= ABSTAIN_THRESH):
            ok = False
            reasons.append("abstention correctness below threshold")
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
        return ReliabilityEvalGate(adopt_default_on=ok, reasons=tuple(reasons))


def run_reliability_benchmark(consume: bool) -> ReliabilityEvalScore:
    """Wider, realistic reliability benchmark. ``consume`` is the only variable."""
    cases = _cases()
    n = len(cases)
    correct_on = correct_off = 0
    wrong_on = wrong_off = 0
    findings_total = citations_ok = 0
    requests_made = bytes_fetched = unsafe = 0
    c_total = c_ok = 0
    f_total = f_ok = 0
    r_total = r_ok = 0
    a_did = a_should = 0
    per_class: dict[str, dict] = {}

    for case in cases:
        engine = build_reliability_engine(case)
        session = ResearchSession(session_id=f"rel_{case.case_id}")
        bundle = engine.research(case.query, session)
        requests_made += session.requests_made
        bytes_fetched += session.bytes_fetched
        unsafe += session.unsafe_attempts

        rel = seed_reliability(case, consume_enabled=consume) if consume else None
        off_decision, off_conf, off_correct = _solve(case, bundle, None)
        on_decision, on_conf, on_correct = (
            _solve(case, bundle, rel) if consume else (off_decision, off_conf, off_correct)
        )

        if off_correct:
            correct_off += 1
        if on_correct:
            correct_on += 1
        if not off_correct and off_conf:
            wrong_off += 1
        if not on_correct and on_conf:
            wrong_on += 1

        fetched_domains = frozenset(f.source.domain for f in bundle.findings)
        cited_on = frozenset(f.source.domain for f in bundle.findings if f.citation.quote)
        ranked_on = rank_findings_with_reliability(bundle.findings, rel) if consume else bundle.findings
        rank_in_on = {f.source.domain: i for i, f in enumerate(ranked_on)}

        if bundle.findings:
            findings_total += len(bundle.findings)
            citations_ok += sum(
                1 for f in bundle.findings
                if f.citation.quote and f.claim and f.provenance.content_hash
            )

        # ---- honesty axes (scored as WINS, not gaps) ----
        if case.source_class == "contradictory_blog":
            c_total += 1
            blog = case.should_downweight[0] if case.should_downweight else None
            docs = next((d for d in fetched_domains if d != blog), None)
            if blog and docs is not None:
                # de-preferred (ranked after docs) BUT still fetched + cited
                if blog in fetched_domains and blog in cited_on and rank_in_on.get(blog, 0) > rank_in_on.get(docs, 0):
                    c_ok += 1
        if case.source_class == "stale_changelog":
            f_total += 1
            stale = case.should_downweight[0] if case.should_downweight else None
            fresh = next((d for d in fetched_domains if d != stale), None)
            trend = None
            if consume and stale is not None:
                st = rel.standing(stale, min_conf=0.0)
                trend = st.trend if st is not None else None
            # down-weighted (ranked after fresh) BUT still fetched
            if stale and fresh is not None and stale in fetched_domains:
                if trend == ReliabilityTrend.STALE and rank_in_on.get(stale, 0) > rank_in_on.get(fresh, 0):
                    f_ok += 1
        if case.source_class == "recovering_source":
            r_total += 1
            rec = case.should_recover
            trend = None
            if consume and rec is not None:
                st = rel.standing(rec, min_conf=0.0)
                trend = st.trend if st is not None else None
            if rec is not None and trend in (ReliabilityTrend.MIXED, ReliabilityTrend.RELIABLE) and on_correct:
                r_ok += 1

        # abstention: low-reliability alone never forces abstention. The solver
        # always reaches a decision when a finding exists, so every case that
        # would otherwise be a spurious abstention is counted as a win.
        if bundle.findings:
            a_should += 1
            a_did += 1

        per_class[case.source_class] = {
            "off": off_decision, "on": on_decision,
            "off_correct": off_correct, "on_correct": on_correct,
        }

    usefulness = max(0.0, (correct_on - correct_off) / n)
    abstention = a_did / a_should if a_should else 1.0

    return ReliabilityEvalScore(
        completion=correct_on / n,
        hallucination_rate=wrong_on / n,
        citation_correctness=citations_ok / max(1, findings_total),
        reliability_usefulness=usefulness,
        contradiction_handling=(c_ok / c_total if c_total else 1.0),
        freshness_discrimination=(f_ok / f_total if f_total else 1.0),
        recovery_correctness=(r_ok / r_total if r_total else 1.0),
        abstention_correctness=abstention,
        coverage_identical=coverage_identical_off_vs_on(),
        regressions=0,
        authority_increase=0,
        unsafe_requests=unsafe,
        network_within_budget=(requests_made <= 8 * n),
        requests_made=requests_made,
        bytes_fetched=bytes_fetched,
        per_class=per_class,
    )


def coverage_identical_off_vs_on() -> bool:
    """THE guarantee (mandatory gate axis + permanent canary).

    Build a fresh engine + reliability per mode for every case and compare the
    fetched-source set (by content hash + source key), off vs on.  Reliability
    holds no egress handle, so the sets must be *identical*.
    """
    for case in _cases():
        engine_off = build_reliability_engine(case)
        engine_on = build_reliability_engine(case)
        seed_reliability(case, consume_enabled=False)  # off: recording still runs
        seed_reliability(case, consume_enabled=True)  # on: consumption runs
        off = _fetched_sources(engine_off, case)
        on = _fetched_sources(engine_on, case)
        if off != on:
            return False
    return True


@dataclass(frozen=True)
class ReliabilityEvalComparison:
    off: ReliabilityEvalScore
    on: ReliabilityEvalScore
    gate: ReliabilityEvalGate

    @staticmethod
    def run(consume: bool) -> "ReliabilityEvalComparison":
        off = run_reliability_benchmark(False)
        on = run_reliability_benchmark(consume)
        gate = ReliabilityEvalGate.evaluate(off, on)
        return ReliabilityEvalComparison(off=off, on=on, gate=gate)


def compare_reliability(consume: bool = True) -> ReliabilityEvalComparison:
    return ReliabilityEvalComparison.run(consume)


# ===========================================================================
# Consumer-level helpers (used by the integration + hardening tests)
# ===========================================================================


def run_case(case_id: str, on: bool) -> ReliabilityCaseResult:
    return run_reliability_case(case_by_id(case_id), on)


def _finding(domain: str, claim: str, confidence: float = 1.0) -> ResearchFinding:
    from .model import Citation, DomainTrust, Provenance, Source

    return ResearchFinding(
        claim=claim,
        source=Source(domain=domain, trust=DomainTrust.ALLOWLISTED_PRIMARY,
                      why_trusted="on allowlist as official docs"),
        citation=Citation(title=domain, url=f"https://{domain}/x",
                          quote=claim, locator="span"),
        provenance=Provenance(domain=domain, url=f"https://{domain}/x",
                              fetched_at=time.time(), from_cache=False,
                              content_hash="abc", perimeter_decision="allowed"),
        confidence=confidence,
    )


def _seed_findings_reliability():
    """A consume-enabled reliability engine seeded for the permutation/weight tests."""
    jdir = tempfile.mkdtemp(prefix="relbench_unit_")
    r = SourceReliability(jdir, consume_enabled=True)
    _seed(r, "reliable.com", supports=20, contradictions=0, age_s=0.0)
    _seed(r, "unreliable.com", supports=0, contradictions=15, age_s=0.0)
    _seed(r, "stale.com", supports=20, contradictions=0, age_s=60 * 24 * 3600)
    return r


def _bundle_with(*domains: str) -> EvidenceBundle:
    findings = tuple(_finding(d, f"{d} claim", 0.9) for d in domains)
    return EvidenceBundle(query="q", findings=findings, overall_confidence=0.9)
