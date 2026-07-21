"""Boundary architecture: inventory production source for direct execution, network, subprocess."""
from __future__ import annotations

import pathlib

import pytest

SOURCE_ROOTS = [pathlib.Path("src/aetheris")]


def _production_py_files():
    files = []
    for root in SOURCE_ROOTS:
        files.extend(root.rglob("*.py"))
    return [f for f in files if "test" not in str(f).lower()]


def _has_direct_tool_run(filepath: pathlib.Path) -> bool:
    text = filepath.read_text(encoding="utf-8")
    if "tool.run(" in text:
        return True
    return False


def _has_direct_requests(filepath: pathlib.Path) -> bool:
    text = filepath.read_text(encoding="utf-8")
    if "requests.post(" in text or "requests.get(" in text:
        return True
    return False


def _has_subprocess_or_socket(filepath: pathlib.Path) -> bool:
    text = filepath.read_text(encoding="utf-8")
    if "subprocess" in text or "socket." in text:
        return True
    return False


_ALLOWLIST = {
    "src/aetheris/model/providers.py",
    "src/aetheris/research/perimeter.py",
    "src/aetheris/safety/guard.py",
    "src/aetheris/tools/builtins.py",
    "src/aetheris/learning/model_patch.py",
}


def test_no_direct_tool_run_in_production():
    violations = []
    for f in _production_py_files():
        rel = str(f).replace("\\", "/")
        if rel in _ALLOWLIST:
            continue
        if _has_direct_tool_run(f):
            violations.append(rel)
    assert not violations, f"direct tool.run() outside SafetyLayer: {violations}"


def test_no_direct_requests_outside_providers():
    violations = []
    for f in _production_py_files():
        rel = str(f).replace("\\", "/")
        if rel in _ALLOWLIST:
            continue
        if _has_direct_requests(f):
            violations.append(rel)
    assert not violations, f"direct requests call outside allowlist: {violations}"


def test_no_subprocess_or_socket_in_production():
    violations = []
    for f in _production_py_files():
        rel = str(f).replace("\\", "/")
        if rel in _ALLOWLIST:
            continue
        if _has_subprocess_or_socket(f):
            violations.append(rel)
    assert not violations, f"subprocess/socket in production: {violations}"


def test_model_failure_falls_back_to_deterministic_planning():
    from aetheris.model import FallbackProvider, MockProvider, ModelRequest, ResponseKind

    fallback = FallbackProvider([MockProvider()])
    req = ModelRequest(kind=ResponseKind.PLAN_SUGGESTION, task="do something", tool_names=("echo",))
    resp = fallback.complete(req)
    assert resp.ok is True
    assert resp.suggestion is None


def test_research_fake_transport_never_called_for_denied_requests():
    from aetheris.research.perimeter import NetworkPerimeter
    from aetheris.research.model import ResearchRequest, ResearchSession, BudgetExceeded

    calls = []
    def fake_transport(req):
        calls.append(req)
        raise AssertionError("transport must not be called for denied requests")

    perimeter = NetworkPerimeter(allowlist=("example.com",), transport=fake_transport)
    session = ResearchSession(
        session_id="s1",
        request_budget=10,
        size_budget=1024,
        rate_budget=10,
        rate_window_s=60.0,
        dry_run=False,
    )
    req = ResearchRequest(url="http://not-https.example.com/page")
    with pytest.raises((BudgetExceeded, Exception)):
        perimeter.fetch(req, session)
    assert not calls, "transport was called for a denied request"
