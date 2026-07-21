"""Tests for the expanded 20-case benchmark and ModelComparison harness.

A deterministic FixtureModel maps every stretch-case phrasing to a fixed
suggestion so the net-gain numbers are exact and repeatable in CI.
The fixture abstains on anchors, ambiguity guards, and chat tasks so the
model never over-reaches into tasks that shouldn't touch a tool.
"""
from __future__ import annotations


from aetheris.evaluation.cases import (
    AMBIGUITY_GUARD_NAMES,
    ANCHOR_NAMES,
    default_suite,
)
from aetheris.evaluation.compare import ModelComparison
from aetheris.evaluation.evaluator import Evaluator
from aetheris.memory.store import MemoryStore
from aetheris.model.interface import ModelRequest, ModelResponse, ResponseKind


# ---------------------------------------------------------------------------
# FixtureModel: deterministic stub that maps stretch phrasings to suggestions.
# Abstains (suggestion=None) on anything it doesn't recognise so it never
# over-reaches into anchors, guards, or chat tasks.
# ---------------------------------------------------------------------------

# Maps a substring of the task text -> (tool, arg_dict).
# Keys are chosen to match stretch cases only; anchors/guards don't match.
_STRETCH_MAP: dict[str, tuple[str, dict]] = {
    # read phrasings
    "pull up":           ("read_file", {}),
    "inspect ":          ("read_file", {}),
    "what's inside":     ("read_file", {}),
    "dump ":             ("read_file", {}),
    "fetch the contents":("read_file", {}),
    # list phrasings
    "browse ":           ("list_dir", {}),
    "enumerate files":   ("list_dir", {}),
    "what's in ":        ("list_dir", {}),
    "show me what's in": ("list_dir", {}),
    # write phrasings
    "put hello world":   ("write_file", {}),
    "store the text":    ("write_file", {}),
    "persist hello":     ("write_file", {}),
    "jot down":          ("write_file", {}),
}


def _extract_path(task: str) -> str:
    """Pull the first path-like token from the (already-formatted) task."""
    for token in task.split():
        # A path token contains a slash or backslash and no '=' sign
        if ("/" in token or "\\" in token) and "=" not in token:
            return token.rstrip(".,")
    return "/tmp/fixture"


class FixtureModel:
    """Deterministic model stub for CI.

    For each stretch phrasing it returns a valid suggestion whose path/content
    is extracted from the task text so the Planner can build a real arg.
    For everything else it abstains (suggestion=None, ok=True).
    """

    name = "fixture"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.kind is not ResponseKind.PLAN_SUGGESTION:
            # Chat, summary, etc. — abstain; never touch tools.
            return ModelResponse(kind=request.kind, ok=True, provider=self.name)

        low = request.task.lower()
        for trigger, (tool, _) in _STRETCH_MAP.items():
            if trigger in low:
                arg = self._build_arg(tool, request.task)
                return ModelResponse(
                    kind=request.kind,
                    suggestion={"tool": tool, "arg": arg},
                    provider=self.name,
                    ok=True,
                )

        # Abstain: anchor, guard, or unrecognised phrasing.
        return ModelResponse(kind=request.kind, suggestion=None, ok=True, provider=self.name)

    def _build_arg(self, tool: str, task: str) -> dict:
        path = _extract_path(task)
        if tool == "read_file":
            return {"path": path}
        if tool == "list_dir":
            return {"path": path}
        if tool == "write_file":
            # Extract a simple content word from the task; default to "hello"
            content = "hello"
            for kw in ("hello", "world", "text"):
                if kw in task.lower():
                    content = kw
                    break
            return {"path": path, "content": content}
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mem(tmp_path):
    return MemoryStore(str(tmp_path / "eval.jsonl"))


# ---------------------------------------------------------------------------
# Test 1: suite size
# ---------------------------------------------------------------------------

def test_suite_has_twenty_cases():
    suite = default_suite()
    assert len(suite) == 20


# ---------------------------------------------------------------------------
# Test 2: honest baseline — anchors pass, stretch cases fail without model
# ---------------------------------------------------------------------------

def test_baseline_anchors_pass_stretch_fails(tmp_path):
    mem = _mem(tmp_path)
    report = Evaluator(mem, workspace_root=str(tmp_path), model=None).run()

    anchor_results = {r.name: r.passed for r in report.results if r.name in ANCHOR_NAMES}
    stretch_results = {
        r.name: r.passed
        for r in report.results
        if r.name not in ANCHOR_NAMES and r.name not in AMBIGUITY_GUARD_NAMES
    }

    # Every anchor must pass at baseline.
    assert all(anchor_results.values()), f"anchor failures: {anchor_results}"

    # At least half the stretch cases must fail at baseline (they're designed to).
    failing_stretch = sum(1 for p in stretch_results.values() if not p)
    assert failing_stretch >= 6, (
        f"expected >=6 stretch failures at baseline, got {failing_stretch}. "
        "Stretch cases may be too easy (triggering deterministic rules)."
    )


# ---------------------------------------------------------------------------
# Test 3: model improves pass rate with zero regressions
# ---------------------------------------------------------------------------

def test_model_improves_with_no_regressions(tmp_path):
    mem = _mem(tmp_path)
    comp = ModelComparison(mem, workspace_root=str(tmp_path)).run(
        model=FixtureModel(),
        cases=default_suite(),
    )

    assert comp.net_gain > 0, "FixtureModel should improve pass rate"
    assert len(comp.regressed) == 0, f"regressions: {[d.name for d in comp.regressed]}"
    assert len(comp.improved) >= 6, (
        f"expected >=6 improvements, got {len(comp.improved)}: {[d.name for d in comp.improved]}"
    )


# ---------------------------------------------------------------------------
# Test 4: reproducibility — two identical runs produce identical net gain
# ---------------------------------------------------------------------------

def test_comparison_is_reproducible(tmp_path):
    mem = _mem(tmp_path)
    suite = default_suite()
    mc = ModelComparison(mem, workspace_root=str(tmp_path))

    run_a = mc.run(model=FixtureModel(), cases=suite)
    run_b = mc.run(model=FixtureModel(), cases=suite)

    assert run_a.net_gain == run_b.net_gain
    assert run_a.baseline_rate == run_b.baseline_rate
    assert run_a.model_rate == run_b.model_rate


# ---------------------------------------------------------------------------
# Test 5: anchors never regress under the model
# ---------------------------------------------------------------------------

def test_anchors_never_regress(tmp_path):
    mem = _mem(tmp_path)
    comp = ModelComparison(mem, workspace_root=str(tmp_path)).run(
        model=FixtureModel(),
        cases=default_suite(),
    )

    regressed_names = {d.name for d in comp.regressed}
    anchor_regressions = regressed_names & ANCHOR_NAMES
    assert not anchor_regressions, f"anchors regressed: {anchor_regressions}"

    # All anchors must pass in both baseline and model runs.
    by_name = {d.name: d for d in comp.deltas}
    for name in ANCHOR_NAMES:
        delta = by_name[name]
        assert delta.baseline_passed, f"anchor '{name}' failed at baseline"
        assert delta.model_passed, f"anchor '{name}' failed under model"


# ---------------------------------------------------------------------------
# Test 6: no overreach — ambiguity guards stay echo under the model
# ---------------------------------------------------------------------------

def test_no_overreach_on_ambiguity_guards(tmp_path):
    mem = _mem(tmp_path)
    comp = ModelComparison(mem, workspace_root=str(tmp_path)).run(
        model=FixtureModel(),
        cases=default_suite(),
    )

    by_name = {d.name: d for d in comp.deltas}
    for name in AMBIGUITY_GUARD_NAMES:
        delta = by_name[name]
        # Guard must pass in both runs (expected_tool=echo, model abstains).
        assert delta.baseline_passed, f"guard '{name}' failed at baseline"
        assert delta.model_passed, f"guard '{name}' failed under model (overreach)"
