"""Tests for Model-Assisted Patching v0.

Canary: ``test_model_off_is_byte_identical``.  With the model off (no patcher),
or the model abstaining/erring/proposing garbage, the repair flow is identical
to deterministic repair.  The model changes the *content* of a repair; it never
touches the *authority* to apply one.

The trust boundary is asserted throughout: a model patch must clear all six
gates or it is rejected and we fall back; a validated proposal is just
``edit_file`` candidate content the unchanged writer can enact.
"""
import json
from typing import Callable

from aetheris.learning.model_patch import (
    ModelAssistedPatcher,
    PatchProposal,
    PatchTestReport,
    parse_diff,
)
from aetheris.memory import ExperienceMemory, OutcomeType
from aetheris.model.interface import ModelRequest, ModelResponse
from aetheris.reflection.engine import ReflectionEngine, StepOutcome, Verdict


# ---------------------------------------------------------------------------
# Fake model providers (text in, text out; never touches the tree)
# ---------------------------------------------------------------------------


class _PatchProvider:
    name = "patch"

    def __init__(self, text: str):
        self._text = text

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(kind=request.kind, text=self._text, provider=self.name, ok=True)


class _GarbageProvider:
    name = "garbage"

    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(kind=request.kind, text="not a diff at all", provider=self.name, ok=True)


class _ErrorProvider:
    name = "error"

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise RuntimeError("model unreachable")


def _outcome(failure_kind: str, tool: str = "edit_file", arg: str = "{}", output: str = "boom") -> StepOutcome:
    return StepOutcome(
        task_id="t1", step_index=0, tool=tool, arg=arg, ok=False,
        output=output, failure_kind=failure_kind,
    )


# ---------------------------------------------------------------------------
# Diff parsing (gate 1)
# ---------------------------------------------------------------------------


def test_parse_diff_well_formed():
    raw = (
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line one\n"
        "-old line\n"
        "+new line\n"
        " line three\n"
    )
    c = parse_diff(raw)
    assert c.parsed
    assert len(c.diffs) == 1
    assert c.diffs[0].path == "src/app.py"
    assert "old line" in c.diffs[0].old_text
    assert "new line" in c.diffs[0].new_text


def test_parse_diff_rejects_garbage():
    assert parse_diff("hello world").parsed is False
    assert parse_diff("").parsed is False


# ---------------------------------------------------------------------------
# The patcher: data, validated, falls back on any failure
# ---------------------------------------------------------------------------


def _make_patcher(root, model, *, experience=None, test_runner=None):
    return ModelAssistedPatcher(
        model, str(root), experience=experience, test_runner=test_runner or _pass_runner(),
    )


def _pass_runner() -> Callable:
    def run(sandbox_root: str) -> PatchTestReport:
        return PatchTestReport(passed=True, regressed=False)
    return run


def _fail_runner() -> Callable:
    def run(sandbox_root: str) -> PatchTestReport:
        return PatchTestReport(passed=False, regressed=False, detail="tests failed")
    return run


def test_propose_repair_valid_patch_returns_edit_file_steps(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("line one\nold line\nline three\n")
    good = (
        "--- a/app.py\n+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line one\n-old line\n+new line\n line three\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(good))
    proposal = patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)})))
    assert isinstance(proposal, PatchProposal)
    assert len(proposal.repair_steps) == 1
    tool, arg = proposal.repair_steps[0]
    assert tool == "edit_file"
    data = json.loads(arg)
    assert data["path"] == "app.py"
    assert "old line" in data["find"]
    assert "new line" in data["replace"]
    # The live tree was never touched.
    assert f.read_text() == "line one\nold line\nline three\n"


def test_propose_repair_never_mutates_live_tree(tmp_path):
    f = tmp_path / "app.py"
    before = "line one\nold line\nline three\n"
    f.write_text(before)
    good = (
        "--- a/app.py\n+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n line one\n-old line\n+new line\n line three\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(good))
    patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)})))
    assert f.read_text() == before  # sandbox discarded; live file unchanged


def test_propose_repair_falls_back_on_garbage(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("x\n")
    patcher = _make_patcher(tmp_path, _GarbageProvider())
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)}))) is None


def test_propose_repair_falls_back_on_model_error(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("x\n")
    patcher = _make_patcher(tmp_path, _ErrorProvider())
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)}))) is None


def test_propose_repair_rejects_out_of_root(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("old line\n")
    # Try to patch a path outside the workspace root.
    bad = (
        "--- a/../escape.py\n+++ b/../escape.py\n"
        "@@ -1,1 +1,1 @@\n-old line\n+new line\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(bad))
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)}))) is None


def test_propose_repair_rejects_sprawl_multi_file(tmp_path):
    (tmp_path / "a.py").write_text("old\n")
    (tmp_path / "b.py").write_text("old\n")
    multi = (
        "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        "--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(multi))
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(tmp_path / 'a.py')}))) is None


def test_propose_repair_rejects_failing_tests(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("old line\n")
    good = (
        "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-old line\n+new line\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(good), test_runner=_fail_runner())
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)}))) is None


def test_propose_repair_extra_scrutiny_on_retired_pattern(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("broken helper\n")
    retired = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True, record_enabled=True)
    retired.record(
        OutcomeType.FAILED_REPEATEDLY, problem="broken helper kept dying", cause="c", fix="f", confidence=0.9,
    )
    retired._store.retire(retired._store.all()[0].id)  # retire it -> retired_lessons() sees it
    good = (
        "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n-broken helper\n+fixed helper\n"
    )
    patcher = _make_patcher(tmp_path, _PatchProvider(good), experience=retired)
    # The new content still contains the retired token -> extra scrutiny rejects.
    assert patcher.propose_repair(_outcome("syntax_error", arg=json.dumps({"path": str(f)}))) is None


# ---------------------------------------------------------------------------
# CANARY: model off == byte-identical deterministic repair
# ---------------------------------------------------------------------------


def _deterministic_steps(reflect, outcome):
    return reflect.reflect(outcome, _plan()).repair_steps


def _plan():
    from aetheris.planner.plan import MultiStepPlan, PlanStep

    return MultiStepPlan(task_id="t1", steps=[PlanStep(tool="edit_file", arg="{}", reason="x")])


def test_model_off_is_byte_identical(tmp_path):
    app = tmp_path / "app.py"
    app.write_text("import os\n")

    # Reflection with NO model patcher: pure deterministic repair.
    ref_off = ReflectionEngine(registry_tools=("edit_file",), understanding=None, reasoning=None)
    off = ref_off.reflect(_outcome("missing_import", arg=json.dumps({"path": str(app)})), _plan())

    # Reflection WITH a patcher whose model is garbage/error: must match the
    # deterministic path exactly (the model is not allowed to change behavior).
    ref_on = ReflectionEngine(
        registry_tools=("edit_file",),
        understanding=None,
        reasoning=None,
        model_patcher=_make_patcher(tmp_path, _GarbageProvider()),
    )
    on = ref_on.reflect(_outcome("missing_import", arg=json.dumps({"path": str(app)})), _plan())

    assert off.verdict == Verdict.INSERT_REPAIR_STEPS
    assert on.verdict == off.verdict
    assert on.repair_steps == off.repair_steps
    assert on.reason == off.reason


def test_model_patch_can_supply_validated_repair_via_reflection(tmp_path):
    app = tmp_path / "app.py"
    app.write_text("line one\nold line\nline three\n")
    good = (
        "--- a/app.py\n+++ b/app.py\n@@ -1,3 +1,3 @@\n line one\n-old line\n+new line\n line three\n"
    )
    ref = ReflectionEngine(
        registry_tools=("edit_file",),
        model_patcher=_make_patcher(tmp_path, _PatchProvider(good)),
    )
    res = ref.reflect(_outcome("syntax_error", arg=json.dumps({"path": str(app)})), _plan())
    assert res.verdict == Verdict.INSERT_REPAIR_STEPS
    assert res.repair_steps and res.repair_steps[0][0] == "edit_file"
    # The verdict content is exactly what the unchanged writer would enact.
    data = json.loads(res.repair_steps[0][1])
    assert "old line" in data["find"] and "new line" in data["replace"]

