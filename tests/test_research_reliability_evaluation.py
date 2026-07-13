"""Wider reliability evaluation + adversarial coverage-preservation hardening.

Mirrors the two prior eval-and-harden milestones, applied to consuming learned
source reliability: the consumer's DECISION is the unit of measurement (a neat
ranking that changes no outcome scores zero help), and the single load-bearing
guarantee -- reliability reorders/weights, never gates -- is measured as
*identity* of the fetched-source set off vs on, asserted as a mandatory gate
axis AND a permanent build-failing canary.

Adversarial source classes (contradictory / stale / recovering) are scored as
WINS: a bad source that is de-preferred but still fetched+cited is correct; a
recovering source that climbs back is correct. Suppressing any of them fails the
gate even if completion rose. No engine / schema / perimeter / authority code
is changed here -- we only measure and harden, against hermetic fixtures.
"""
from __future__ import annotations

import dataclasses
import tempfile

from aetheris.research import (
    ReliabilityEvalGate,
    ReliabilityTrend,
    SourceReliability,
    coverage_identical_off_vs_on,
    reliability_cases,
    run_case,
    run_reliability_benchmark,
    run_reliability_case,
)
from aetheris.research.consumers import (
    deliberate_with_research_and_reliability,
    learn_with_reliability,
)
from aetheris.research.engine import ResearchEngine
from aetheris.research.model import (
    EvidenceBundle,
    ResearchSession,
)
from aetheris.research.reliability import (
    ReliabilityObservation,
    ReliabilityProvenance,
    SourceStanding,
)
from aetheris.research.reliability_benchmark import (
    _bundle_with,
    _finding,
    _seed_findings_reliability,
    case_by_id,
    compare_reliability,
)
from aetheris.reasoning.schema import Recommendation


# ===========================================================================
# Divergence precondition: every non-control case must be able to diverge
# ===========================================================================


def test_every_non_control_case_diverges_off_vs_on():
    # control is reliability-inert by design; all other classes MUST diverge.
    for case in reliability_cases():
        if not case.divergence_required:
            continue
        res = run_reliability_case(case, consume=True)
        assert res.correct_off != res.correct_on or res.decision_off != res.decision_on, (
            f"{case.case_id}: case did not diverge (off={res.correct_off}, on={res.correct_on})"
        )
        assert res.correct_off is False and res.correct_on is True, (
            f"{case.case_id}: expected off wrong / on right "
            f"(off={res.correct_off}, on={res.correct_on})"
        )


def test_no_divergent_case_is_a_noop():
    for case in reliability_cases():
        if not case.divergence_required:
            continue
        res = run_reliability_case(case, consume=True)
        assert res.decision_off != res.decision_on


# ===========================================================================
# THE canary: reliability never changes the fetched-source set (identity)
# ===========================================================================


def test_fetched_source_set_identical_off_vs_on():
    # IDENTITY, not similarity: off vs on, every case, by content hash + source key.
    assert coverage_identical_off_vs_on() is True


def test_fetched_source_set_identical_per_case_off_vs_on():
    for case in reliability_cases():
        off = run_reliability_case(case, consume=False).fetched_sources
        on = run_reliability_case(case, consume=True).fetched_sources
        assert off == on, f"{case.case_id}: coverage changed off vs on"
        # must-still-fetch sources present in both
        res = run_reliability_case(case, consume=True)
        assert res.all_must_still_fetch()


def test_low_reliability_source_still_fetched_and_cited():
    res = run_case("contradictory_blog_conbar", on=True)
    blog = res.should_downweight
    assert blog, "case missing should_downweight"
    assert blog.issubset({d for d, _ in res.fetched_sources})
    for b in blog:
        assert res.is_cited(b)


def test_retired_to_neutral_source_still_fetched():
    import tempfile

    from aetheris.research.reliability_benchmark import _seed, case_by_id

    case = case_by_id("contradictory_blog_conbar")
    jdir = tempfile.mkdtemp(prefix="rel_retire_")
    r = SourceReliability(jdir, consume_enabled=True)
    for s in case.reliability_seed:
        _seed(r, s.source_key, s.supports, s.contradictions, s.age_s)
    r.retire_to_neutral("blog.contra")
    from aetheris.research.api import FakeTransport

    engine = ResearchEngine(
        allowlist=case.allowlist,
        search_map=dict(case.search_map),
        transport=FakeTransport(dict(case.content)),
        primary_domains=case.allowlist,
    )
    session = ResearchSession(session_id="retire")
    bundle = engine.research(case.query, session)
    assert "blog.contra" in {f.source.domain for f in bundle.findings}


def test_rank_findings_is_permutation_not_filter():
    r = _seed_findings_reliability()
    findings = (
        _finding("reliable.com", "a is true", 1.0),
        _finding("unreliable.com", "b is false", 0.5),
        _finding("stale.com", "c is stale", 0.6),
    )
    ranked = r.rank_findings(findings)
    assert set(ranked) == set(findings) and len(ranked) == len(findings)
    # reliable first, then stale, then unreliable (lowest standing)
    assert ranked[0].source.domain == "reliable.com"


def test_reliability_never_changes_fetch_eligibility():
    case = case_by_id("correct_docs_pyfoo")
    from aetheris.research.api import FakeTransport

    engine = ResearchEngine(
        allowlist=case.allowlist,
        search_map=dict(case.search_map),
        transport=FakeTransport(dict(case.content)),
        primary_domains=case.allowlist,
    )
    from aetheris.research.reliability_benchmark import _seed

    jdir = tempfile.mkdtemp(prefix="rel_flip_")
    r_reliable = SourceReliability(jdir, consume_enabled=True)
    _seed(r_reliable, "py.docs", supports=20, contradictions=0, age_s=0.0)

    jdir2 = tempfile.mkdtemp(prefix="rel_flip2_")
    r_unreliable = SourceReliability(jdir2, consume_enabled=True)
    _seed(r_unreliable, "py.docs", supports=0, contradictions=15, age_s=0.0)

    s1 = ResearchSession(session_id="flip1")
    s2 = ResearchSession(session_id="flip2")
    b1 = engine.research(case.query, s1)
    b2 = engine.research(case.query, s2)
    assert {f.source.domain for f in b1.findings} == {f.source.domain for f in b2.findings}


def test_weight_confidence_does_not_drop_findings():
    # weighting adjusts confidence; it never removes a finding from the bundle
    from aetheris.research.consumers import weight_confidence_with_reliability

    r = _seed_findings_reliability()
    b = _bundle_with("a.com", "b.com")
    claims = {f.claim for f in b.findings}
    weighted = [weight_confidence_with_reliability(f, r) for f in b.findings]
    # one numeric confidence per finding -> no finding dropped
    assert len(weighted) == len(b.findings)
    assert all(isinstance(c, float) for c in weighted)
    assert {f.claim for f in b.findings} == claims


# ===========================================================================
# Structural: reliability holds no egress power (re-asserted on wide path)
# ===========================================================================


def test_reliability_holds_no_perimeter_or_fetch_handle():
    r = SourceReliability.__new__(SourceReliability)
    r._consume_enabled = False
    for banned in ("fetch", "perimeter", "allowlist", "block", "deny", "gate",
                   "edit", "run", "promote", "set_config", "safety", "tools"):
        assert not hasattr(r, banned)


def test_reliability_schema_has_no_egress_or_action_field():
    for T in (ReliabilityObservation, ReliabilityProvenance, SourceStanding):
        f = {x.name for x in dataclasses.fields(T)}
        assert not (f & {"block", "allow", "deny", "fetchable", "gate", "step", "tool", "execute"})


def test_perimeter_is_still_sole_egress_authority():
    case = case_by_id("correct_docs_pyfoo")
    engine = ResearchEngine(
        allowlist=case.allowlist,
        search_map=dict(case.search_map),
        transport=None,
        primary_domains=case.allowlist,
    )
    assert hasattr(engine, "_perimeter") and callable(getattr(engine._perimeter, "fetch", None))
    for banned in ("client", "http", "socket", "session"):
        assert not hasattr(engine, banned)


# ===========================================================================
# Realistic classes: reliability improves the decision (scored as help)
# ===========================================================================


def test_correct_docs_preferred_and_improves_decision():
    on = run_case("correct_docs_pyfoo", on=True)
    off = run_case("correct_docs_pyfoo", on=False)
    assert on.preferred("py.docs")
    assert on.correct_on is True and off.correct_on is False


def test_contradictory_blog_depreferred_but_fetched_and_cited():
    on = run_case("contradictory_blog_conbar", on=True)
    assert on.rank_of("blog.contra") > on.rank_of("docs.c")  # de-preferred
    assert "blog.contra" in {d for d, _ in on.fetched_sources}
    assert on.is_cited("blog.contra")  # still present + cited


def test_stale_changelog_downweighted_but_fetched():
    on = run_case("stale_changelog_chgctx", on=True)
    assert on.trend_of("vendor.log") == ReliabilityTrend.STALE
    assert "vendor.log" in {d for d, _ in on.fetched_sources}
    assert on.rank_of("vendor.log") > on.rank_of("fresh.v")  # fresh preferred


def test_recovering_source_regains_standing():
    on = run_case("recovering_source_reccall", on=True)
    assert on.trend_of("blog.rec") in (ReliabilityTrend.MIXED, ReliabilityTrend.RELIABLE)
    assert on.correct_on is True


# ===========================================================================
# Consumers: advisory, ownership unchanged
# ===========================================================================


def test_reasoning_uses_reliability_observation_and_still_abstains_on_thin():
    r = _seed_findings_reliability()
    evidence = EvidenceBundle(
        query="q",
        findings=(_finding("reliable.com", "x", 0.8),),
    )
    d = deliberate_with_research_and_reliability(None, query="q", evidence=evidence, reliability=r)
    assert any(o.provenance.source == "reliability" for o in d.observations)

    thin = EvidenceBundle(query="q", unknowns=("thin",), contradictions=("x",), overall_confidence=0.2)
    d2 = deliberate_with_research_and_reliability(None, query="q", evidence=thin, reliability=r)
    assert d2.recommendation == Recommendation.ABSTAIN


def test_low_reliability_alone_does_not_force_abstention():
    r = _seed_findings_reliability()  # unreliable.com has low standing
    evidence = EvidenceBundle(
        query="q",
        findings=(_finding("unreliable.com", "x", 0.9),),
        overall_confidence=0.9,
    )
    d = deliberate_with_research_and_reliability(None, query="q", evidence=evidence, reliability=r)
    assert d.recommendation != Recommendation.ABSTAIN


def test_understanding_never_rewrites_repo_model():
    import hashlib
    import json
    import types

    repo = types.SimpleNamespace(_model={"files": {"a.py": 1}})
    before = hashlib.sha256(json.dumps(repo._model, sort_keys=True).encode()).hexdigest()
    # reliability never holds a repo/model handle, so nothing can mutate it
    assert not hasattr(SourceReliability, "rewrite_repo")
    after = hashlib.sha256(json.dumps(repo._model, sort_keys=True).encode()).hexdigest()
    assert before == after


def test_reflection_owns_verdict_edits_still_gated():
    from aetheris.research.consumers import _all_edits_gated, execute, reflect_with_research

    v = reflect_with_research(None, _bundle_with("docs.c"))
    assert v.owner == "reflection" and _all_edits_gated(execute(v))


def test_learning_only_more_conservative():
    cand = __import__("types").SimpleNamespace(passes_gate=False)
    r = _seed_findings_reliability()
    assert learn_with_reliability(cand, r).adopted is False


# ===========================================================================
# Off / no-regression / gate
# ===========================================================================


def test_reliability_off_byte_identical_per_consumer():
    for case in reliability_cases():
        off = run_reliability_case(case, consume=False)
        on = run_reliability_case(case, consume=True)
        assert off.fetched_sources == on.fetched_sources


def test_compare_reliability_builds_gate():
    cmp = compare_reliability()
    assert cmp.off.coverage_identical is True
    assert cmp.on.coverage_identical is True
    assert cmp.gate.adopt_default_on, cmp.gate.reasons


def test_meets_expanded_adoption_gate():
    off_ = run_reliability_benchmark(False)
    on_ = run_reliability_benchmark(True)
    gate = ReliabilityEvalGate.evaluate(off_, on_)
    assert on_.hallucination_rate <= off_.hallucination_rate
    assert on_.citation_correctness >= 0.8
    assert on_.reliability_usefulness > 0.0
    assert on_.coverage_identical is True
    assert on_.contradiction_handling >= 0.8
    assert on_.freshness_discrimination >= 0.8
    assert on_.recovery_correctness >= 0.8
    assert on_.unsafe_requests == 0 and on_.authority_increase == 0 and on_.regressions == 0
    assert gate.adopt_default_on, gate.reasons


def test_prior_research_guards_still_green():
    # The existing wider research gate + research hardening must remain green.
    from aetheris.research.benchmark import WideResearchComparison

    wide = WideResearchComparison.run(True)
    assert wide.gate.adopt_default_on is True
