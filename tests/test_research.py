"""Research Engine v0 — tests (structural guarantees first).

Mirrors the acceptance criteria in the design doc (§7): the engine is
structurally incapable of acting; the NetworkPerimeter is deny-wins on every
rule; evidence is immutable and honest; consumers are optional/ignorable;
research off is byte-identical to Hierarchical v0; and the adoption gate is the
absolute clause (one unsafe request fails it). Research is the only variable.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import tempfile
import types

import pytest

from aetheris.research import (
    ALLOWLIST,
    DomainTrust,
    EvidenceBundle,
    FakeTransport,
    GATE_CITATION_THRESHOLD as THRESH,
    NetworkPerimeter,
    PerimeterDenied,
    Provenance,
    RawResponse,
    ResearchEngine,
    ResearchFinding,
    ResearchJournal,
    ResearchRequest,
    ResearchSession,
    Source,
    Citation,
    BudgetExceeded,
    SEARCH_MAP,
    annotate_symbol_with_research,
    baseline_hierarchical_v0,
    compare,
    deliberate_with_research,
    execute,
    learn_with_research,
    off,
    on,
    on_with_injected_unsafe_attempt,
    reflect_with_research,
    run_benchmark,
    _all_edits_gated,
)
from aetheris.reasoning.schema import Recommendation


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _journal():
    return ResearchJournal(tempfile.mkdtemp(prefix="research_test_"))


def _engine(transport=None, search_map=None):
    return ResearchEngine(
        ALLOWLIST,
        search_map=search_map if search_map is not None else dict(SEARCH_MAP),
        journal=_journal(),
        transport=transport or FakeTransport(dict(_CONTENT())),
    )


def _perimeter(transport=None):
    return NetworkPerimeter(ALLOWLIST, transport=transport or FakeTransport(dict(_CONTENT())))


def _session(**kw):
    return ResearchSession(session_id="s", **kw)


def _req(url="https://docs.allowed.com/x", **kw):
    return ResearchRequest(url=url, **kw)


def _CONTENT():
    return {
        "https://docs.allowed.com/api/foo": "The signature of foo is foo(a: int) -> bool.",
        "https://docs.allowed.com/errors/e42": "Error E42 is caused by a missing config.",
        "https://docs.allowed.com/api/bar": "bar returns str.",
        "https://docs2.allowed.com/bar": "bar returns int.",
    }


def _over_cap():
    return 300 * 1024


def _fetch_n(perimeter, session, n):
    for i in range(n):
        perimeter.fetch(_req(f"https://docs.allowed.com/{i}"), session)


def _only_network_path_is(engine, _path):
    for banned in ("client", "http", "socket", "session", "transport"):
        if hasattr(engine, banned):
            return False
    return hasattr(engine, "_perimeter") and callable(getattr(engine._perimeter, "fetch", None))


def _no_bytes_left_machine(engine):
    tr = getattr(engine._perimeter, "_transport", None)
    return tr is None or len(getattr(tr, "egress_calls", [])) == 0


def _no_request_outside_session():
    try:
        _perimeter().fetch(_req(), None)
    except (PerimeterDenied, BudgetExceeded):
        return True
    return False


def _no_background_crawler_thread(engine):
    return not any(hasattr(engine, a) for a in ("thread", "crawler", "daemon"))


def _sample_finding():
    return ResearchFinding(
        claim="foo(a: int) -> bool",
        source=Source(domain="docs.allowed.com", trust=DomainTrust.ALLOWLISTED_PRIMARY,
                      why_trusted="on allowlist as official docs"),
        citation=Citation(title="docs", url="https://docs.allowed.com/api/foo",
                          quote="foo(a: int) -> bool", locator="span"),
        provenance=Provenance(domain="docs.allowed.com", url="https://docs.allowed.com/api/foo",
                              fetched_at=1.0, from_cache=False, content_hash="abc",
                              perimeter_decision="allowed"),
        confidence=1.0,
    )


def _doc_bundle():
    return EvidenceBundle(query="q", findings=(_sample_finding(),), overall_confidence=1.0)


def _thin_bundle():
    return EvidenceBundle(query="q", unknowns=("thin",), contradictions=("x",), overall_confidence=0.2)


def _contradicting_bundle():
    return EvidenceBundle(query="q", contradictions=("sources disagree",), overall_confidence=0.3)


def _repo_model_hash(repo):
    return hashlib.sha256(json.dumps(repo._model, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# §7 — structural incapacity to act (the hard guarantee)                      #
# --------------------------------------------------------------------------- #

def test_engine_holds_no_execution_authority():
    r = _engine()
    for banned in ("edit", "run", "shell", "write_file", "mutate_plan",
                   "promote", "set_config", "safety", "tools", "executive"):
        assert not hasattr(r, banned)


def test_evidence_schema_cannot_express_an_action():
    for T in (EvidenceBundle, ResearchFinding, Provenance, Citation, Source):
        fields = {f.name for f in dataclasses.fields(T)}
        assert not (fields & {"step", "tool", "command", "edit", "post", "plan", "execute"})


def test_evidence_is_immutable():
    b = _doc_bundle()
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.overall_confidence = 0.99


def test_no_egress_except_through_perimeter():
    assert _only_network_path_is(_engine(), "NetworkPerimeter.fetch")


# --------------------------------------------------------------------------- #
# §7 — perimeter: deny-wins on every rule                                     #
# --------------------------------------------------------------------------- #

def test_non_allowlisted_domain_is_denied():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req("https://evil.example.com"), _session())


def test_non_https_is_denied():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req("http://docs.allowed.com"), _session())


def test_redirect_off_allowlist_is_denied():
    class RedirectTransport:
        def __init__(self, final):
            self.final = final
            self.egress_calls = []

        def __call__(self, req):
            self.egress_calls.append(req.url)
            return RawResponse(url=req.url, final_url=self.final, status=200,
                               content_type="text/plain", content=b"x",
                               redirect_count=1, from_cache=False,
                               auth_sent=False, cookies_sent=False, js_executed=False)

    p = NetworkPerimeter(ALLOWLIST, transport=RedirectTransport("http://evil.example.com"))
    with pytest.raises(PerimeterDenied):
        p.fetch(_req("https://docs.allowed.com/x"), _session())


def test_budgets_close_session_when_exceeded():
    s = _session(request_budget=2)
    _fetch_n(_perimeter(), s, 2)
    with pytest.raises(BudgetExceeded):
        _perimeter().fetch(_req(), s)


def test_mime_and_size_limits_enforced():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req(declared_mime="application/octet-stream"), _session())
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req(declared_size=_over_cap()), _session())


def test_robots_respected():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req(disallowed_by_robots=True), _session())


def test_no_auth_no_cookies_no_js():
    resp = _perimeter().fetch(_req(), _session())
    assert not resp.auth_sent and not resp.cookies_sent and not resp.js_executed


def test_dry_run_emits_zero_egress():
    eng = _engine()
    s = _session(dry_run=True)
    b = eng.research("what is the signature of foo", s)
    assert b.dry_run and b.bytes_fetched == 0 and _no_bytes_left_machine(eng)


def test_sessions_are_task_scoped_no_background():
    assert _no_request_outside_session() and _no_background_crawler_thread(_engine())


# --------------------------------------------------------------------------- #
# §7 — evidence honesty: contradictions, unknowns, provenance                 #
# --------------------------------------------------------------------------- #

def test_conflicting_sources_recorded_as_contradictions():
    b = _engine().research("what does bar return", _session())
    assert b.contradictions and b.overall_confidence < 0.6


def test_absent_evidence_yields_unknowns_not_fabrication():
    b = _engine().research("what is the meaning of xyzqq life", _session())
    assert b.unknowns and not b.findings


def test_every_finding_has_full_provenance_and_citation():
    b = _engine().research("what is the signature of foo", _session())
    for f in b.findings:
        assert f.provenance.domain and f.provenance.content_hash and f.citation.quote
        assert f.source.why_trusted


# --------------------------------------------------------------------------- #
# §7 — consumers: optional, ignorable, ownership unchanged                    #
# --------------------------------------------------------------------------- #

def test_reasoning_uses_research_but_still_abstains_on_thin():
    d = deliberate_with_research(None, evidence=_thin_bundle())
    assert d.recommendation == Recommendation.ABSTAIN


def test_understanding_annotates_without_mutating_repo_model():
    repo = types.SimpleNamespace(_model={"files": {"a.py": 1}})
    before = _repo_model_hash(repo)
    annotate_symbol_with_research(repo, "foo", _doc_bundle())
    assert _repo_model_hash(repo) == before       # external evidence never rewrites AST facts


def test_reflection_owns_verdict_edits_still_gated():
    v = reflect_with_research(types.SimpleNamespace(), _doc_bundle())
    assert v.owner == "reflection" and _all_edits_gated(execute(v))


def test_learning_only_more_conservative_with_research():
    cand = types.SimpleNamespace(passes_gate=False)
    assert learn_with_research(cand, _contradicting_bundle()).adopted is False


# --------------------------------------------------------------------------- #
# §7 — off / no-regression / gate                                             #
# --------------------------------------------------------------------------- #

def test_research_off_is_byte_identical_to_hierarchical_v0():
    assert run_benchmark(off()) == baseline_hierarchical_v0()


def test_meets_adoption_gate():
    off_ = compare(research=off())
    on_ = compare(research=on())
    assert on_.completion >= off_.completion
    assert (on_.hallucination <= off_.hallucination
            and on_.citation_correctness >= THRESH)
    assert on_.regressions == 0 and on_.authority_increase == 0
    assert on_.unsafe_requests == 0 and on_.network_within_budget
    assert on_.gate.adopt_default_on


def test_single_unsafe_request_fails_the_gate():
    res = compare(research=on_with_injected_unsafe_attempt())
    assert res.gate.adopt_default_on is False   # absolute clause
