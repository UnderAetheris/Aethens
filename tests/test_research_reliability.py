"""Research Reliability Learning v0 — tests (canary + structural + behavior).

Mirrors the acceptance criteria in the design doc (§8): reliability is a
weighting, never a gate; schema carries no egress/action fields; observations
immutable; rank_findings is a permutation; three decays work; reversible
retirement to neutral; coverage canary; consumers advisory; off is byte-
identical. No new authority; no perimeter change; no allowlist change.
"""
from __future__ import annotations

import dataclasses
import tempfile
import time
import types

import pytest

from aetheris.research.consumers import (
    deliberate_with_research_and_reliability,
    learn_with_reliability,
)
from aetheris.research.model import (
    Citation,
    DomainTrust,
    EvidenceBundle,
    Provenance,
    ResearchFinding,
    ResearchSession,
    Source,
)
from aetheris.research.api import FakeTransport
from aetheris.research.engine import ResearchEngine
from aetheris.research.reliability import (
    ReliabilityObservation,
    ReliabilityProvenance,
    ReliabilityTrend,
    SourceReliability,
    SourceStanding,
)
from aetheris.reasoning.schema import Recommendation


# ===========================================================================
# Helpers
# ===========================================================================


def _jr():
    return tempfile.mkdtemp(prefix="reliability_test_")


def _reliability(consume: bool = False):
    return SourceReliability(_jr(), consume_enabled=consume)


def _sample_obs():
    prov = ReliabilityProvenance(
        source_key="py.docs",
        supports=5,
        contradictions=1,
        window="last_6_events",
        last_confirmed_at=time.time(),
        evidence_events=("e1", "e2", "e3"),
    )
    return ReliabilityObservation(
        source_key="py.docs",
        trend=ReliabilityTrend.RELIABLE,
        confidence=0.8,
        freshness=0.9,
        note="consistently validated",
        provenance=prov,
        retired=False,
    )


def _finding(domain, claim, confidence=1.0):
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


def _run_fetch(domain, query="foo"):
    content = {f"https://{domain}/x": f"The signature of {query} is {query}(a: int) -> bool."}
    engine = ResearchEngine(
        allowlist=(domain,),
        search_map={query.split()[0]: [f"https://{domain}/x"]},
        transport=FakeTransport(content),
    )
    session = ResearchSession(session_id="r")
    return engine.research(f"what is {query}", session)


# ===========================================================================
# Structural: reliability cannot gate egress or express an action
# ===========================================================================


def test_reliability_holds_no_perimeter_or_fetch_handle():
    r = _reliability()
    for banned in ("fetch", "perimeter", "allowlist", "block", "deny",
                   "edit", "run", "promote", "set_config", "safety", "tools"):
        assert not hasattr(r, banned)


def test_reliability_schema_has_no_egress_or_action_field():
    for T in (ReliabilityObservation, ReliabilityProvenance, SourceStanding):
        f = {x.name for x in dataclasses.fields(T)}
        assert not (f & {"block", "allow", "deny", "fetchable", "step", "tool", "execute", "edit"})


def test_observations_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_sample_obs(), "confidence", 0.99)


# ===========================================================================
# THE canary: reliability never reduces coverage
# ===========================================================================


def test_low_reliability_source_is_still_fetched_and_cited():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("blog-x.example", validated=False, contradicted=True, event_id=f"bx{i}")
        r.retire_to_neutral("blog-x.example")
        b = _run_fetch("blog-x.example", query="foo")
        sources_fetched = {f.source.domain for f in b.findings}
        assert "blog-x.example" in sources_fetched


def test_ranking_is_a_permutation_not_a_filter():
    findings = (_finding("reliable.com", "a is true", 1.0),
                _finding("unreliable.com", "b is false", 0.5))
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("reliable.com", validated=True, contradicted=False, event_id=f"r{i}")
        for i in range(15):
            r.record_outcome("unreliable.com", validated=False, contradicted=True, event_id=f"u{i}")
        ranked = r.rank_findings(findings)
        assert set(ranked) == set(findings) and len(ranked) == len(findings)


# ===========================================================================
# Deterministic learning + three decays
# ===========================================================================


def test_reliable_source_gains_standing_from_validated_outcomes():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("py.docs", validated=True, contradicted=False, event_id=f"e{i}")
        obs = r.standing("py.docs")
        assert obs is not None
        assert obs.trend == ReliabilityTrend.RELIABLE


def test_contradiction_decays_standing():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("py.docs", validated=True, contradicted=False, event_id=f"e{i}")
        for i in range(15):
            r.record_outcome("blog-x.example", validated=False, contradicted=True, event_id=f"bx{i}")
        r.apply_decay()
        obs = r.standing("blog-x.example", min_conf=0.0)
        assert obs is not None
        assert obs.trend == ReliabilityTrend.UNRELIABLE


def test_freshness_decay_marks_stale_after_version():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("vendor.docs", validated=True, contradicted=False, event_id=f"e{i}")
        r.apply_decay(now=time.time() + 31 * 24 * 3600)
        obs = r.standing("vendor.docs", min_conf=0.0)
        assert obs is not None
        assert obs.trend == ReliabilityTrend.STALE


def test_confidence_is_deterministic():
    with tempfile.TemporaryDirectory() as jdir:
        r1 = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r1.record_outcome("s", validated=True, contradicted=False, event_id=f"e{i}")
        c1 = r1.standing("s", min_conf=0.0).confidence
        r2 = SourceReliability(_jr(), consume_enabled=True)
        for i in range(20):
            r2.record_outcome("s", validated=True, contradicted=False, event_id=f"e{i}")
        c2 = r2.standing("s", min_conf=0.0).confidence
        assert c1 == c2


# ===========================================================================
# Reversible retirement to NEUTRAL (not blacklist)
# ===========================================================================


def test_retire_withdraws_preference_not_reach():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("blog-x.example", validated=False, contradicted=True, event_id=f"bx{i}")
        r.retire_to_neutral("blog-x.example")
        obs = r.standing("blog-x.example", min_conf=0.0)
        assert obs is not None
        assert obs.retired is True
        b = _run_fetch("blog-x.example", query="foo")
        assert "blog-x.example" in {f.source.domain for f in b.findings}


def test_retirement_is_reversible_and_bounded():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("blog-x.example", validated=False, contradicted=True, event_id=f"bx{i}")
        r.retire_to_neutral("blog-x.example")
        assert r.standing("blog-x.example", min_conf=0.0).retired is True
        r.unretire("blog-x.example")
        assert r.standing("blog-x.example", min_conf=0.0).retired is False


def test_recovering_source_regains_standing():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(15):
            r.record_outcome("blog-x.example", validated=False, contradicted=True, event_id=f"bx{i}")
        for i in range(25):
            r.record_outcome("blog-x.example", validated=True, contradicted=False, event_id=f"g{i}")
        obs = r.standing("blog-x.example")
        assert obs is not None
        assert obs.trend in (ReliabilityTrend.MIXED, ReliabilityTrend.RELIABLE)


def test_nothing_deleted_history_preserved():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("py.docs", validated=True, contradicted=False, event_id=f"e{i}")
        pre_len = r._store.count()
        r.retire_to_neutral("py.docs")
        assert r._store.count() >= pre_len


# ===========================================================================
# Consumers: advisory, ownership unchanged
# ===========================================================================


def test_reasoning_uses_reliability_as_observation_and_still_abstains_on_thin():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(20):
            r.record_outcome("docs.allowed.com", validated=True, contradicted=False, event_id=f"e{i}")

        evidence = EvidenceBundle(
            query="q",
            findings=(ResearchFinding(
                claim="x",
                source=Source(domain="docs.allowed.com", trust=DomainTrust.ALLOWLISTED_PRIMARY,
                              why_trusted="on allowlist"),
                citation=Citation(title="t", url="u", quote="x", locator="l"),
                provenance=Provenance(domain="docs.allowed.com", url="u",
                                      fetched_at=1.0, from_cache=False,
                                      content_hash="h", perimeter_decision="allowed"),
                confidence=0.8,
            ),),
        )

        d = deliberate_with_research_and_reliability(None, query="q", evidence=evidence, reliability=r)
        assert any(o.provenance.source == "reliability" for o in d.observations)

        thin = EvidenceBundle(query="q", unknowns=("thin",), contradictions=("x",), overall_confidence=0.2)
        d2 = deliberate_with_research_and_reliability(None, query="q", evidence=thin, reliability=r)
        assert d2.recommendation == Recommendation.ABSTAIN


def test_understanding_never_rewrites_repo_model():
    import hashlib
    import json
    repo = types.SimpleNamespace(_model={"files": {"a.py": 1}})
    before = hashlib.sha256(json.dumps(repo._model, sort_keys=True).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        r.standing("docs.allowed.com")
    after = hashlib.sha256(json.dumps(repo._model, sort_keys=True).encode()).hexdigest()
    assert before == after


def test_learning_only_more_conservative():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        cand = types.SimpleNamespace(passes_gate=False)
        result = learn_with_reliability(cand, r)
        assert result.adopted is False


def test_abstention_not_triggered_by_low_reliability_alone():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=True)
        for i in range(15):
            r.record_outcome("docs.allowed.com", validated=False, contradicted=True, event_id=f"bx{i}")
        for i in range(25):
            r.record_outcome("docs.allowed.com", validated=True, contradicted=False, event_id=f"g{i}")

        evidence = EvidenceBundle(
            query="q",
            findings=(ResearchFinding(
                claim="x",
                source=Source(domain="docs.allowed.com", trust=DomainTrust.ALLOWLISTED_PRIMARY,
                              why_trusted="on allowlist"),
                citation=Citation(title="t", url="u", quote="x", locator="l"),
                provenance=Provenance(domain="docs.allowed.com", url="u",
                                      fetched_at=1.0, from_cache=False,
                                      content_hash="h", perimeter_decision="allowed"),
                confidence=0.9,
            ),),
            overall_confidence=0.9,
        )
        d = deliberate_with_research_and_reliability(None, query="q", evidence=evidence, reliability=r)
        assert d.recommendation != Recommendation.ABSTAIN


# ===========================================================================
# Off / no-regression / gate
# ===========================================================================


def test_reliability_off_is_none_when_consumption_gated():
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=False)
        obs = r.standing("py.docs")
        assert obs is None


def test_reliability_rank_off_is_byte_identical():
    findings = (_finding("a.com", "a"), _finding("b.com", "b"))
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=False)
        assert r.rank_findings(findings) == findings


def test_reliability_weight_off_passthrough():
    f = _finding("a.com", "a", confidence=0.8)
    with tempfile.TemporaryDirectory() as jdir:
        r = SourceReliability(jdir, consume_enabled=False)
        assert r.weight_confidence(f) == 0.8
