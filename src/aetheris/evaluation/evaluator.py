from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..controller.controller import Controller
from ..memory.store import MemoryStore
from ..planner.planner import Plan, Planner
from .cases import EvalCase, default_suite


class _RecordingPlanner:
    """Wraps a Planner and remembers the last Plan it produced.

    Lets the evaluator see the planned tool without changing the controller.
    """

    def __init__(self, inner: Planner) -> None:
        self._inner = inner
        self.last: Plan | None = None

    def plan(self, task: str) -> Plan:
        self.last = self._inner.plan(task)
        return self.last


@dataclass
class CaseResult:
    name: str
    passed: bool
    detail: str


@dataclass
class Report:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


class Evaluator:
    """Runs benchmark cases through a real Controller, scores them, logs results."""

    def __init__(self, memory: MemoryStore, workspace_root: str) -> None:
        self._memory = memory
        self._root = Path(workspace_root)

    def run(self, cases: list[EvalCase] | None = None) -> Report:
        cases = cases if cases is not None else default_suite()
        report = Report()

        for case in cases:
            result = self._run_case(case)
            report.results.append(result)
            self._memory.record(
                "eval_case",
                {"name": case.name, "passed": result.passed, "detail": result.detail},
            )

        self._memory.record(
            "eval_summary",
            {
                "ts": time.time(),
                "passed": report.passed,
                "total": report.total,
                "pass_rate": round(report.pass_rate, 4),
            },
        )
        return report

    def _run_case(self, case: EvalCase) -> CaseResult:
        if case.fixture is not None:
            rel, content = case.fixture
            (self._root / rel).write_text(content, encoding="utf-8")

        task = case.task.format(root=str(self._root))

        controller = Controller(
            Config(
                log_path=str(self._root / "eval_run.jsonl"),
                workspace_root=str(self._root),
            )
        )
        recorder = _RecordingPlanner(controller.planner)
        controller.planner = recorder

        result = controller.handle(task)
        planned_tool = recorder.last.tool if recorder.last else None

        checks: list[str] = []
        ok = True

        if case.expected_tool is not None:
            tool_ok = planned_tool == case.expected_tool
            ok &= tool_ok
            checks.append(f"tool {planned_tool}=={case.expected_tool}:{tool_ok}")

        if case.expected_output is not None:
            out_ok = result.output == case.expected_output
            ok &= out_ok
            checks.append(f"output=={case.expected_output!r}:{out_ok}")

        return CaseResult(name=case.name, passed=ok, detail="; ".join(checks) or "no-asserts")
