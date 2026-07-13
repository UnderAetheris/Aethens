"""Research Default-On Hardening v1 — tests (milestone §4).

These re-assert the structural guarantees against the configuration users
actually run (research ON by default), prove the opt-out is a true rollback that
seals the network boundary, and confirm both standing CI guards still pass. No
engine / schema / perimeter / safety / authority change is exercised here; we
only verify the flip + enforcement. The one production change is
``research_enabled`` defaulting to True; everything else guards it.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
import types

import pytest

from aetheris.api.state import AppState
from aetheris.config import Config, resolve_research_enabled
from aetheris.research import (
    EvidenceBundle,
    ResearchFinding,
    PerimeterDenied,
    ResearchRequest,
    ResearchSession,
    Citation,
    Provenance,
    Source,
    DomainTrust,
    baseline_hierarchical_v0,
    run_benchmark,
)
from aetheris.research.benchmark import (
    compare_wide,
    run_wide_benchmark,
)
from aetheris.research.consumers import (
    annotate_symbol_with_research,
    learn_with_research,
    reflect_with_research,
    _all_edits_gated,
)


# ===========================================================================
# Helpers
# ===========================================================================


def run_suite(path: str) -> types.SimpleNamespace:
    import os

    cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", path, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": os.path.join(cwd, "src")},
    )
    return types.SimpleNamespace(all_passed=result.returncode == 0)


def _req(url="https://not-on-allowlist.com", **kw):
    return ResearchRequest(url=url, **kw)


def _session(**kw):
    return ResearchSession(session_id="d", **kw)


def _only_network_path_is(engine, _path):
    for banned in ("client", "http", "socket", "session", "transport"):
        if banned == "transport":
            continue
        if hasattr(engine, banned):
            return False
    return hasattr(engine, "_perimeter") and callable(getattr(engine._perimeter, "fetch", None))


def _sample_bundle():
    return EvidenceBundle(
        query="q",
        findings=(ResearchFinding(
            claim="x", source=Source(domain="d", trust=DomainTrust.ALLOWLISTED_PRIMARY,
                                     why_trusted="t"),
            citation=Citation(title="t", url="u", quote="x", locator="l"),
            provenance=Provenance(domain="d", url="u", fetched_at=1.0, from_cache=False,
                                  content_hash="h", perimeter_decision="allowed"),
        ),),
    )


# ===========================================================================
# Default-on wiring
# ===========================================================================


def test_default_config_enables_research(tmp_path):
    assert Config().research_enabled is True
    app = AppState.create(root=str(tmp_path / "data"), config=Config(), env={})
    assert app.research is not None


def test_env_optout_forces_off_and_is_true_rollback(tmp_path):
    app = AppState.create(
        root=str(tmp_path / "data"), config=Config(), env={"AETHERIS_RESEARCH": "off"}
    )
    # The NetworkPerimeter is never constructed; the boundary is fully sealed.
    assert app.research is None
    # The off-path is byte-identical to the Hierarchical v0 baseline.
    assert run_benchmark(app.research is not None) == baseline_hierarchical_v0()


def test_malformed_env_defers_to_config_never_forces_on(tmp_path):
    on = AppState.create(
        root=str(tmp_path / "on"), config=Config(research_enabled=True),
        env={"AETHERIS_RESEARCH": "maybe"},
    )
    off = AppState.create(
        root=str(tmp_path / "off"), config=Config(research_enabled=False),
        env={"AETHERIS_RESEARCH": "maybe"},
    )
    assert on.research is not None
    assert off.research is None


def test_resolve_precedence_is_explicit(tmp_path):
    cfg = Config(research_enabled=True)
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "off"}) is False
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "0"}) is False
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "false"}) is False
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "on"}) is True
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "1"}) is True
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "true"}) is True
    # unset / malformed -> config default, never silently forced on
    assert resolve_research_enabled(cfg, {}) is True
    assert resolve_research_enabled(cfg, {"AETHERIS_RESEARCH": "garbage"}) is True
    # ambiguity resolves toward less egress: config off is honored
    assert resolve_research_enabled(Config(research_enabled=False), {"AETHERIS_RESEARCH": "garbage"}) is False


# ===========================================================================
# Guarantees re-asserted on the default-on (live) path
# ===========================================================================


def test_engine_no_execution_authority_default_on(tmp_path):
    r = AppState.create(
        root=str(tmp_path / "data"), config=Config(), env={}
    ).research
    for banned in ("edit", "run", "shell", "write_file", "mutate_plan",
                   "promote", "set_config", "safety", "tools", "executive"):
        assert not hasattr(r, banned)


def test_evidence_schema_no_action_field_default_on():
    for T in (EvidenceBundle, ResearchFinding, Provenance, Citation, Source):
        f = {x.name for x in dataclasses.fields(T)}
        assert not (f & {"step", "tool", "command", "edit", "post", "plan", "execute"})


def test_evidence_immutable_default_on():
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(_sample_bundle(), "overall_confidence", 0.99)


def test_only_egress_path_is_perimeter_default_on(tmp_path):
    r = AppState.create(root=str(tmp_path / "data"), config=Config(), env={}).research
    assert _only_network_path_is(r, "NetworkPerimeter.fetch")


def test_deny_wins_on_default_path(tmp_path):
    r = AppState.create(root=str(tmp_path / "data"), config=Config(), env={}).research
    with pytest.raises(PerimeterDenied):
        r._perimeter.fetch(_req("https://not-on-allowlist.com"), _session())


def test_zero_unsafe_requests_on_default_path():
    on = run_wide_benchmark(True)
    assert on.unsafe_requests == 0 and on.network_within_budget


def test_authority_neutral_on_default_path():
    on = run_wide_benchmark(True)
    assert on.authority_increase == 0 and on.regressions == 0


def test_owners_keep_ownership_default_on(tmp_path):
    v = reflect_with_research(types.SimpleNamespace(), _sample_bundle())
    assert v.owner == "reflection"
    assert _all_edits_gated(v.proposed_edits)
    cand = types.SimpleNamespace(passes_gate=False)
    assert learn_with_research(cand, _sample_bundle()).adopted is False
    repo = types.SimpleNamespace(_model={"files": {"a.py": 1}})
    out = annotate_symbol_with_research(repo, "foo", _sample_bundle())
    assert "external" in out


def test_ci_gates_still_pass():
    # The expanded help-gate.
    assert compare_wide(research=True).gate.adopt_default_on is True
    # The absolute unsafe-request clause.
    assert compare_wide(research="on_unsafe_wide").gate.adopt_default_on is False


def test_hardening_suite_unchanged_and_green():
    from pathlib import Path

    suite = Path(__file__).parent / "test_research_hardening.py"
    assert run_suite(str(suite)).all_passed
