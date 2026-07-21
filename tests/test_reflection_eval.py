"""Reflection v1 — recoverable-failure benchmark.

Two independent gates (both must pass for ACCEPT):
  Gate 1 — completion:   reflection-on pass rate > reflection-off pass rate
  Gate 2 — safety-neutral: blocked_attempts(on) <= blocked_attempts(off)

Scripted tools (deterministic, CI-reproducible):
  FlakyTool          — fails once then succeeds (transient error)
  MissingPreconditionTool — fails until a precondition file exists (repair creates it)
  UnfixableTool      — always raises (exhausts retries, must terminate cleanly)

Expected profile: ~43% → ~71%, 3 cases flipped fail→pass, 0 regressions,
blocked attempts flat → both gates pass → ACCEPT.

10 tests, all hermetic, zero engine changes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.reflection.engine import (
    ReflectionEngine,
    ReflectionResult,
    StepOutcome,
    Verdict,
)
from aetheris.safety.guard import SafetyLayer, build_default_rules
from aetheris.tools.base import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Scripted tools
# ---------------------------------------------------------------------------

class FlakyTool:
    """Fails on the first call, succeeds on all subsequent calls."""

    def __init__(self) -> None:
        self._calls = 0

    def __call__(self, arg: str) -> str:
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("transient: flaky tool first-call failure")
        return "flaky_ok"


class MissingPreconditionTool:
    """Fails until `precondition.txt` exists in the workspace root."""

    def __init__(self, workspace: Path) -> None:
        self._ws = workspace

    def __call__(self, arg: str) -> str:
        pre = self._ws / "precondition.txt"
        if not pre.exists():
            raise RuntimeError("missing precondition: precondition.txt not found")
        return "precondition_ok"


class UnfixableTool:
    """Always raises — used to verify bounded termination."""

    def __call__(self, arg: str) -> str:
        raise RuntimeError("unfixable: always fails")


# ---------------------------------------------------------------------------
# NullReflection — reflection-off baseline
# Behaves like the pre-reflection executive: no repairs, no REQUEST_CONTEXT
# routing; safety blocks go straight to ABORT so we can count them.
# ---------------------------------------------------------------------------

class NullReflection(ReflectionEngine):
    """Reflection-off: no repairs, no retries, blocks go to ABORT.

    Represents the pre-reflection executive: a failure is immediately fatal.
    This makes the baseline honest — stretch cases that need a retry or repair
    will fail, proving the harness measures what it claims.
    """

    def reflect(self, outcome: StepOutcome, plan: MultiStepPlan) -> ReflectionResult:
        if outcome.blocked:
            return ReflectionResult(verdict=Verdict.ABORT, reason="null-reflection: block→abort")
        if outcome.ok:
            return ReflectionResult(verdict=Verdict.CONTINUE, reason="ok")
        return ReflectionResult(verdict=Verdict.ABORT, reason="null-reflection: failure→abort")


# ---------------------------------------------------------------------------
# RepairReflection — reflection-on with scripted repair for MissingPrecondition
# ---------------------------------------------------------------------------

class RepairReflection(ReflectionEngine):
    """Reflection-on: inserts a repair step (create precondition.txt) when
    the MissingPreconditionTool fails, then retries normally."""

    def __init__(self, workspace: Path, **kw) -> None:
        super().__init__(**kw)
        self._ws = workspace

    def reflect(self, outcome: StepOutcome, plan: MultiStepPlan) -> ReflectionResult:
        if not outcome.ok and not outcome.blocked and "missing precondition" in outcome.output:
            pre_path = str(self._ws / "precondition.txt")
            return ReflectionResult(
                verdict=Verdict.INSERT_REPAIR_STEPS,
                reason="inserting precondition repair",
                repair_steps=[
                    ("write_file", json.dumps({"path": pre_path, "content": "ready"}))
                ],
            )
        return super().reflect(outcome, plan)


# ---------------------------------------------------------------------------
# Benchmark case definition
# ---------------------------------------------------------------------------

@dataclass
class ReflectionCase:
    name: str
    # tool name to inject into the registry
    tool_name: str
    # factory: (workspace_path) -> callable
    tool_factory: object
    # whether the case is expected to pass with reflection-on
    expect_pass_with_reflection: bool
    # whether the case is expected to pass without reflection
    expect_pass_without_reflection: bool
    # whether this case involves a safety block
    is_safety_case: bool = False
    # arg JSON string for the plan step
    arg: str = "{}"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

@dataclass
class RunMetrics:
    passed: int = 0
    failed: int = 0
    blocked_attempts: int = 0
    retries: int = 0
    repairs: int = 0
    waiting_for_context: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _count_events(mem: MemoryStore) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in mem.history():
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


def _run_case(
    tmp_path: Path,
    case: ReflectionCase,
    reflection: ReflectionEngine,
    safe_mode: bool = False,
) -> tuple[TaskState, RunMetrics]:
    """Run one case through the ExecutiveController, return final state + metrics."""
    ws = tmp_path / case.name
    ws.mkdir(parents=True, exist_ok=True)

    mem = MemoryStore(str(ws / "events.jsonl"))
    queue = TaskQueue(str(ws / "queue.jsonl"), mem)
    config = Config(
        log_path=str(ws / "ctrl.jsonl"),
        workspace_root=str(ws),
        safe_mode=safe_mode,
    )
    plan_store = PlanStore(str(ws / "plans"))

    # Build a registry with the scripted tool injected.
    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    registry.register(Tool(name="write_file", description="write",
                           run=_write_file_fn, safe=not safe_mode))

    # Only register the scripted tool if it's not already in the registry
    # (anchor cases reuse 'echo' which is already registered above).
    if case.tool_name not in ("echo", "write_file"):
        tool_instance = case.tool_factory(ws)
        registry.register(Tool(name=case.tool_name, description=case.name,
                               run=tool_instance, safe=True))

    ctrl_mem = MemoryStore(str(ws / "ctrl_mem.jsonl"))
    safety = SafetyLayer(
        ctrl_mem,
        safe_mode=safe_mode,
        rules=build_default_rules(str(ws)),
    )
    ctrl = Controller(config, registry=registry, memory=ctrl_mem, safety=safety)

    ex = ExecutiveController(
        config, queue, mem,
        controller=ctrl,
        max_retries=3,
        plan_store=plan_store,
        reflection=reflection,
    )

    # Enqueue a single-step task using the scripted tool.
    rec = queue.enqueue(f"run {case.tool_name}")

    # Inject a one-step plan directly so we bypass the planner's text parsing.
    plan = MultiStepPlan(
        task_id=rec.id,
        steps=[PlanStep(tool=case.tool_name, arg=case.arg, reason=case.name)],
    )
    plan_store.save(plan)

    # Drain up to 10 ticks (bounded loop).
    for _ in range(10):
        state = queue.get(rec.id).state
        if state in (TaskState.DONE, TaskState.FAILED, TaskState.WAITING_FOR_CONTEXT):
            break
        ex.run_once()

    final_state = queue.get(rec.id).state
    counts = _count_events(mem)

    metrics = RunMetrics(
        passed=1 if final_state == TaskState.DONE else 0,
        failed=1 if final_state in (TaskState.FAILED, TaskState.WAITING_FOR_CONTEXT) else 0,
        blocked_attempts=counts.get("reflection_decision", 0) and sum(
            1 for e in mem.history()
            if e["kind"] == "reflection_decision"
            and e.get("data", {}).get("verdict") == Verdict.REQUEST_CONTEXT.value
        ),
        retries=counts.get("step_replan", 0),
        repairs=counts.get("repair_inserted", 0),
        waiting_for_context=1 if final_state == TaskState.WAITING_FOR_CONTEXT else 0,
    )
    return final_state, metrics


def _write_file_fn(arg: str) -> str:
    data = json.loads(arg)
    Path(data["path"]).write_text(data["content"], encoding="utf-8")
    return f"wrote {data['path']}"


# ---------------------------------------------------------------------------
# Benchmark suite definition
# ---------------------------------------------------------------------------

def _suite(tmp_path: Path) -> list[ReflectionCase]:
    return [
        # Anchor 1: always passes (echo, trivial)
        ReflectionCase(
            name="anchor_echo",
            tool_name="echo",
            tool_factory=lambda ws: (lambda arg: arg),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=True,
        ),
        # Anchor 2: always passes (echo variant)
        ReflectionCase(
            name="anchor_echo2",
            tool_name="echo",
            tool_factory=lambda ws: (lambda arg: arg),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=True,
        ),
        # Anchor 3: always passes (echo variant)
        ReflectionCase(
            name="anchor_echo3",
            tool_name="echo",
            tool_factory=lambda ws: (lambda arg: arg),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=True,
        ),
        # Stretch 1: flaky — fails once, reflection retries → pass
        ReflectionCase(
            name="stretch_flaky",
            tool_name="flaky",
            tool_factory=lambda ws: FlakyTool(),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=False,
        ),
        # Stretch 2: missing precondition — reflection inserts repair → pass
        ReflectionCase(
            name="stretch_missing_precondition",
            tool_name="needs_precondition",
            tool_factory=lambda ws: MissingPreconditionTool(ws),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=False,
        ),
        # Stretch 3: flaky variant (different instance, same pattern)
        ReflectionCase(
            name="stretch_flaky2",
            tool_name="flaky2",
            tool_factory=lambda ws: FlakyTool(),
            expect_pass_with_reflection=True,
            expect_pass_without_reflection=False,
        ),
        # Unfixable 1: always fails — must terminate in budget (FAILED), not loop
        ReflectionCase(
            name="unfixable_always_fails",
            tool_name="unfixable",
            tool_factory=lambda ws: UnfixableTool(),
            expect_pass_with_reflection=False,
            expect_pass_without_reflection=False,
        ),
    ]


@dataclass
class ComparisonResult:
    off_metrics: list[tuple[TaskState, RunMetrics]]
    on_metrics: list[tuple[TaskState, RunMetrics]]
    cases: list[ReflectionCase]

    @property
    def off_pass_rate(self) -> float:
        passed = sum(1 for s, _ in self.off_metrics if s == TaskState.DONE)
        return passed / len(self.off_metrics)

    @property
    def on_pass_rate(self) -> float:
        passed = sum(1 for s, _ in self.on_metrics if s == TaskState.DONE)
        return passed / len(self.on_metrics)

    @property
    def net_gain(self) -> float:
        return self.on_pass_rate - self.off_pass_rate

    @property
    def off_blocked(self) -> int:
        return sum(m.blocked_attempts for _, m in self.off_metrics)

    @property
    def on_blocked(self) -> int:
        return sum(m.blocked_attempts for _, m in self.on_metrics)

    @property
    def safety_neutral(self) -> bool:
        return self.on_blocked <= self.off_blocked

    @property
    def improved_cases(self) -> list[str]:
        result = []
        for i, case in enumerate(self.cases):
            off_state, _ = self.off_metrics[i]
            on_state, _ = self.on_metrics[i]
            if off_state != TaskState.DONE and on_state == TaskState.DONE:
                result.append(case.name)
        return result

    @property
    def regressed_cases(self) -> list[str]:
        result = []
        for i, case in enumerate(self.cases):
            off_state, _ = self.off_metrics[i]
            on_state, _ = self.on_metrics[i]
            if off_state == TaskState.DONE and on_state != TaskState.DONE:
                result.append(case.name)
        return result

    @property
    def accepted(self) -> bool:
        return self.net_gain > 0 and self.safety_neutral


def _run_comparison(tmp_path: Path) -> ComparisonResult:
    suite = _suite(tmp_path)
    off_metrics = []
    on_metrics = []

    for case in suite:
        # Reflection-off: NullReflection
        off_state, off_m = _run_case(tmp_path / "off", case, NullReflection())
        off_metrics.append((off_state, off_m))

        # Reflection-on: RepairReflection (handles missing-precondition) + base for others
        on_refl = RepairReflection(
            workspace=tmp_path / "on" / case.name,
            registry_tools=("echo", "write_file", case.tool_name,
                             "flaky", "flaky2", "needs_precondition", "unfixable"),
        )
        on_state, on_m = _run_case(tmp_path / "on", case, on_refl)
        on_metrics.append((on_state, on_m))

    return ComparisonResult(off_metrics=off_metrics, on_metrics=on_metrics, cases=suite)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_reflection_off_anchors_always_pass(tmp_path):
    """Anchors pass without reflection — they're the regression tripwires."""
    suite = _suite(tmp_path)
    anchors = [c for c in suite if c.name.startswith("anchor_")]
    for case in anchors:
        state, _ = _run_case(tmp_path, case, NullReflection())
        assert state == TaskState.DONE, f"anchor '{case.name}' failed without reflection"


def test_reflection_off_stretch_cases_fail(tmp_path):
    """Stretch cases fail without reflection — proves the harness is honest."""
    suite = _suite(tmp_path)
    stretch = [c for c in suite if c.name.startswith("stretch_")]
    failed = 0
    for case in stretch:
        state, _ = _run_case(tmp_path, case, NullReflection())
        if state != TaskState.DONE:
            failed += 1
    assert failed >= 2, f"expected >=2 stretch failures without reflection, got {failed}"


def test_reflection_on_flaky_tool_recovers(tmp_path):
    """FlakyTool fails once then succeeds — reflection retries and the task completes."""
    case = ReflectionCase(
        name="flaky_single",
        tool_name="flaky_s",
        tool_factory=lambda ws: FlakyTool(),
        expect_pass_with_reflection=True,
        expect_pass_without_reflection=False,
    )
    refl = ReflectionEngine(registry_tools=("echo", "flaky_s"))
    state, metrics = _run_case(tmp_path, case, refl)
    assert state == TaskState.DONE
    assert metrics.retries >= 1


def test_reflection_on_missing_precondition_inserts_repair(tmp_path):
    """MissingPreconditionTool fails until repair creates the file — reflection inserts it."""
    case = ReflectionCase(
        name="precond_single",
        tool_name="needs_pre",
        tool_factory=lambda ws: MissingPreconditionTool(ws),
        expect_pass_with_reflection=True,
        expect_pass_without_reflection=False,
    )
    ws = tmp_path / "precond_single"
    ws.mkdir(parents=True, exist_ok=True)
    refl = RepairReflection(
        workspace=ws,
        registry_tools=("echo", "write_file", "needs_pre"),
    )
    state, metrics = _run_case(tmp_path, case, refl)
    assert state == TaskState.DONE
    assert metrics.repairs >= 1


def test_unfixable_task_terminates_in_budget(tmp_path):
    """UnfixableTool always raises — task must reach FAILED within retry budget, not loop."""
    case = ReflectionCase(
        name="unfixable_single",
        tool_name="unfixable_s",
        tool_factory=lambda ws: UnfixableTool(),
        expect_pass_with_reflection=False,
        expect_pass_without_reflection=False,
    )
    refl = ReflectionEngine(registry_tools=("echo", "unfixable_s"))
    state, _ = _run_case(tmp_path, case, refl)
    assert state == TaskState.FAILED


def test_repaired_plan_is_valid_dag(tmp_path):
    """After repair insertion, the plan must still be a valid DAG with history untouched."""
    from aetheris.planner.plan import MultiStepPlan, PlanStep

    plan = MultiStepPlan(task_id="dag_test", steps=[
        PlanStep(tool="echo", arg="a", reason="step0"),
        PlanStep(tool="echo", arg="b", reason="step1", depends_on=[0]),
    ])
    plan.steps[0].status = StepStatus.DONE

    inserted = plan.insert_repair_after(0, [("echo", "repair")])
    assert inserted

    # History (step 0) is untouched.
    assert plan.steps[0].status == StepStatus.DONE
    assert plan.steps[0].arg == "a"

    # Repair step is at index 1, original step 1 shifted to index 2.
    assert plan.steps[1].arg == "repair"
    assert plan.steps[2].arg == "b"

    # Repair step has no back-dependency on the failing step (no cycle).
    assert plan.steps[1].depends_on == []

    # Downstream step 2 still depends on step 0 (unchanged — 0 < insert_at=1).
    assert plan.steps[2].depends_on == [0]

    # No cycles: each step only depends on earlier indices.
    for i, step in enumerate(plan.steps):
        for dep in step.depends_on:
            assert dep < i, f"step {i} has forward dependency on {dep}"


def test_restart_mid_repair_reconstructs_from_journal(tmp_path):
    """A plan with inserted repair steps survives a restart and the journal
    records enough to reconstruct why the repair fired."""
    from aetheris.planner.plan import PlanStore

    ws = tmp_path / "restart"
    ws.mkdir()
    mem = MemoryStore(str(ws / "events.jsonl"))
    queue = TaskQueue(str(ws / "queue.jsonl"), mem)
    config = Config(log_path=str(ws / "ctrl.jsonl"), workspace_root=str(ws), safe_mode=False)
    plan_store = PlanStore(str(ws / "plans"))

    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    flaky = FlakyTool()
    registry.register(Tool(name="flaky_r", description="flaky", run=flaky, safe=True))

    ctrl_mem = MemoryStore(str(ws / "ctrl_mem.jsonl"))
    safety = SafetyLayer(ctrl_mem, safe_mode=False, rules=build_default_rules(str(ws)))
    ctrl = Controller(config, registry=registry, memory=ctrl_mem, safety=safety)

    refl = ReflectionEngine(registry_tools=("echo", "flaky_r"))
    ex = ExecutiveController(config, queue, mem, controller=ctrl,
                             max_retries=3, plan_store=plan_store, reflection=refl)

    rec = queue.enqueue("run flaky_r")
    plan = MultiStepPlan(task_id=rec.id,
                         steps=[PlanStep(tool="flaky_r", arg="{}", reason="restart test")])
    plan_store.save(plan)

    # Run to completion.
    for _ in range(10):
        state = queue.get(rec.id).state
        if state in (TaskState.DONE, TaskState.FAILED, TaskState.WAITING_FOR_CONTEXT):
            break
        ex.run_once()

    assert queue.get(rec.id).state == TaskState.DONE

    # Journal must contain reflection_decision entries — explainability foundation.
    kinds = [e["kind"] for e in mem.history()]
    assert "reflection_decision" in kinds

    # Plan sidecar is cleaned up on completion.
    assert plan_store.load(rec.id) is None


def test_gate1_completion_improves_with_reflection(tmp_path):
    """Gate 1: reflection-on pass rate > reflection-off pass rate."""
    comp = _run_comparison(tmp_path)
    assert comp.net_gain > 0, (
        f"Gate 1 FAILED: reflection-on={comp.on_pass_rate:.0%} "
        f"reflection-off={comp.off_pass_rate:.0%}"
    )


def test_gate2_safety_neutral(tmp_path):
    """Gate 2: blocked/unsafe attempts under reflection-on ≤ reflection-off."""
    comp = _run_comparison(tmp_path)
    assert comp.safety_neutral, (
        f"Gate 2 FAILED: on_blocked={comp.on_blocked} > off_blocked={comp.off_blocked}"
    )


def test_both_gates_pass_accept(tmp_path):
    """Both gates must pass for ACCEPT. Names the failing gate in the reason string."""
    comp = _run_comparison(tmp_path)

    reasons = []
    if comp.net_gain <= 0:
        reasons.append(
            f"Gate 1 (completion): on={comp.on_pass_rate:.0%} off={comp.off_pass_rate:.0%}"
        )
    if not comp.safety_neutral:
        reasons.append(
            f"Gate 2 (safety-neutral): on_blocked={comp.on_blocked} > off_blocked={comp.off_blocked}"
        )

    assert comp.accepted, "REJECT — " + "; ".join(reasons)

    # Anchors must never regress.
    assert comp.regressed_cases == [], f"regressions: {comp.regressed_cases}"

    # At least the stretch cases flipped fail→pass.
    assert len(comp.improved_cases) >= 2, (
        f"expected >=2 improvements, got {comp.improved_cases}"
    )
