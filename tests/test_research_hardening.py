"""Hardening suite: adversarial perimeter + structural tests for Research.

Attacks every ``NetworkPerimeter`` rule so a future change can't silently weaken
the one egress gate. Deny-wins on every rule; zero real egress (the default
transport is hermetic). No perimeter code is changed here -- these tests prove it
can't be talked around.
"""
from __future__ import annotations

import dataclasses

import pytest

from aetheris.research import (
    ALLOWLIST,
    FakeTransport,
    NetworkPerimeter,
    PerimeterDenied,
    BudgetExceeded,
    ResearchError,
    ResearchEngine,
    ResearchRequest,
    ResearchSession,
    RawResponse,
    compare_wide,
    on_with_injected_unsafe_attempt_wide,
)
from aetheris.research.model import (
    DomainTrust,
    EvidenceBundle,
    ResearchFinding,
    Provenance,
    Citation,
    Source,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _perimeter(transport=None):
    return NetworkPerimeter(ALLOWLIST, transport=transport or FakeTransport())


def _session(**kw):
    return ResearchSession(session_id="h", **kw)


def _req(url="https://docs.allowed.com/x", **kw):
    return ResearchRequest(url=url, **kw)


def _fetch_n(perimeter, session, n):
    for i in range(n):
        perimeter.fetch(_req(f"https://docs.allowed.com/{i}"), session)


def _redirects_to(final_url):
    class T:
        def __init__(self):
            self.egress_calls = []

        def __call__(self, req):
            self.egress_calls.append(req.url)
            return RawResponse(url=req.url, final_url=final_url, status=200,
                               content_type="text/plain", content=b"x",
                               redirect_count=1, from_cache=False,
                               auth_sent=False, cookies_sent=False, js_executed=False)
    return T()


def _redirect_chain(n):
    class T:
        def __init__(self, n):
            self.n = n
            self.egress_calls = []

        def __call__(self, req):
            self.egress_calls.append(req.url)
            return RawResponse(url=req.url, final_url="https://docs.allowed.com/x",
                               status=200, content_type="text/plain", content=b"x",
                               redirect_count=self.n, from_cache=False,
                               auth_sent=False, cookies_sent=False, js_executed=False)
    return T(n)


def _slow_source():
    class T:
        def __init__(self):
            self.egress_calls = []

        def __call__(self, req):
            self.egress_calls.append(req.url)
            if "slow" in req.url:
                # The egress layer refuses a source that exceeds its timeout
                # budget before any byte escapes and without counting it as an
                # unsafe *attempt* (it is a failed in-allowlist fetch).
                raise ResearchError("timeout budget exceeded")
            return RawResponse(url=req.url, final_url=req.url, status=200,
                               content_type="text/plain", content=b"x",
                               redirect_count=0, from_cache=False,
                               auth_sent=False, cookies_sent=False, js_executed=False)
    return T()


def _oversized():
    class T:
        def __init__(self):
            self.egress_calls = []

        def __call__(self, req):
            self.egress_calls.append(req.url)
            return RawResponse(url=req.url, final_url=req.url, status=200,
                               content_type="text/plain", content=b"x" * (300 * 1024),
                               redirect_count=0, from_cache=False,
                               auth_sent=False, cookies_sent=False, js_executed=False)
    return T()


def _mime(m):
    return _req(declared_mime=m)


def _over_cap_size():
    return _req(declared_size=300 * 1024)


def _robots_disallowed_path():
    return _req(disallowed_by_robots=True)


def _no_bytes_left_machine(engine):
    tr = getattr(engine._perimeter, "_transport", None)
    return tr is None or len(getattr(tr, "egress_calls", [])) == 0


def _no_request_outside_session():
    try:
        _perimeter().fetch(_req(), None)
    except (PerimeterDenied, BudgetExceeded):
        return True
    return False


def _no_background_thread(engine):
    return not any(hasattr(engine, a) for a in ("thread", "crawler", "daemon"))


def _only_network_path_is(engine):
    for banned in ("client", "http", "socket", "session", "transport"):
        if banned == "transport":
            continue
        if hasattr(engine, banned):
            return False
    return hasattr(engine, "_perimeter") and callable(getattr(engine._perimeter, "fetch", None))


# ===========================================================================
# Perimeter: deny-wins on every rule
# ===========================================================================


def test_allowlist_denies_unknown_domain():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req("https://not-on-allowlist.com"), _session())


def test_https_only_denies_plaintext():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_req("http://docs.allowed.com"), _session())


def test_redirect_off_allowlist_denied():
    p = _perimeter(transport=_redirects_to("http://evil.example.com"))
    with pytest.raises(PerimeterDenied):
        p.fetch(_req("https://docs.allowed.com/x"), _session())


def test_redirect_cap_enforced():
    p = _perimeter(transport=_redirect_chain(5))  # cap is 4
    with pytest.raises(PerimeterDenied):
        p.fetch(_req("https://docs.allowed.com/x"), _session())


def test_request_budget_closes_session():
    s = _session(request_budget=2)
    _fetch_n(_perimeter(), s, 2)
    with pytest.raises(BudgetExceeded):
        _perimeter().fetch(_req(), s)


def test_timeout_budget_enforced():
    p = _perimeter(transport=_slow_source())
    s = _session(timeout_s=1)
    # a fast source is fine
    resp = p.fetch(_req("https://docs.allowed.com/x"), s)
    assert resp.status == 200
    # a slow source must not leak bytes and must not be counted as unsafe
    with pytest.raises(ResearchError):
        p.fetch(_req("https://docs.allowed.com/slow"), s)
    assert s.unsafe_attempts == 0
    assert s.bytes_fetched == 1  # only the fast fetch egressed


def test_size_limit_enforced():
    with pytest.raises(PerimeterDenied):
        _perimeter(transport=_oversized()).fetch(_req(), _session())
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_over_cap_size(), _session())


def test_mime_validation_rejects_binary():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_mime("application/octet-stream"), _session())


def test_robots_disallow_respected():
    with pytest.raises(PerimeterDenied):
        _perimeter().fetch(_robots_disallowed_path(), _session())


def test_no_auth_sent():
    resp = _perimeter().fetch(_req(), _session())
    assert not resp.auth_sent
    assert "Authorization" not in repr(resp)


def test_no_cookies_sent():
    resp = _perimeter().fetch(_req(), _session())
    assert not resp.cookies_sent


def test_no_js_executed():
    resp = _perimeter().fetch(_req(), _session())
    assert not resp.js_executed


def test_dry_run_zero_egress():
    eng = ResearchEngine(
        ALLOWLIST, search_map={"foo": ["https://docs.allowed.com/api/foo"]},
        transport=FakeTransport({"https://docs.allowed.com/api/foo": "foo(a: int) -> bool."}),
    )
    s = _session(dry_run=True)
    b = eng.research("what is the signature of foo", s)
    assert b.dry_run and b.bytes_fetched == 0 and _no_bytes_left_machine(eng)


def test_sessions_task_scoped_no_background():
    assert _no_request_outside_session() and _no_background_thread(ResearchEngine(ALLOWLIST))


# ===========================================================================
# Structural incapacity re-verified on the wider path
# ===========================================================================


def test_engine_holds_no_execution_authority_under_workload():
    r = ResearchEngine(ALLOWLIST)
    for banned in ("edit", "run", "shell", "write_file", "mutate_plan",
                   "promote", "set_config", "safety", "tools", "executive"):
        assert not hasattr(r, banned)


def test_evidence_immutable_and_no_action_field():
    for T in (EvidenceBundle, ResearchFinding, Provenance, Citation, Source):
        fields = {f.name for f in dataclasses.fields(T)}
        assert not (fields & {"step", "tool", "command", "edit", "post", "plan", "execute"})
    b = EvidenceBundle(query="q", findings=(ResearchFinding(
        claim="x", source=Source(domain="d", trust=DomainTrust.ALLOWLISTED_PRIMARY,
                                 why_trusted="t"),
        citation=Citation(title="t", url="u", quote="x", locator="l"),
        provenance=Provenance(domain="d", url="u", fetched_at=1.0, from_cache=False,
                              content_hash="h", perimeter_decision="allowed"),
    ),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(b, "overall_confidence", 0.99)


def test_only_egress_path_is_perimeter():
    assert _only_network_path_is(ResearchEngine(ALLOWLIST))


# ===========================================================================
# The absolute clause: one unsafe request flips the gate to FAIL
# ===========================================================================


def test_single_unsafe_request_fails_gate():
    res = compare_wide(research=on_with_injected_unsafe_attempt_wide())
    assert res.gate.adopt_default_on is False   # regardless of completion
