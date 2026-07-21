from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config
from ..controller.controller import Controller
from ..controller.queue import TaskQueue, TaskState
from ..memory.store import MemoryStore
from ..planner.plan import PlanStore
from ..planner.planner import Planner
from ..safety.guard import SafetyLayer, build_default_rules
from ..skills.registry import SkillRegistry
from ..tools.base import Tool, ToolRegistry
from .cases import EvalCase, WorkflowCase, default_suite
from .evaluator import Evaluator, Report

if TYPE_CHECKING:
    from ..model import ModelProvider


# ---------------------------------------------------------------------------
# Model comparison (unchanged)
# ---------------------------------------------------------------------------

@dataclass
class CaseDelta:
    """Records the difference in outcome for a single case between baseline and model runs."""

    name: str
    baseline_passed: bool
    model_passed: bool

    @property
    def changed(self) -> bool:
        return self.baseline_passed != self.model_passed

    @property
    def improved(self) -> bool:
        return (not self.baseline_passed) and self.model_passed

    @property
    def regressed(self) -> bool:
        return self.baseline_passed and (not self.model_passed)


@dataclass
class Comparison:
    """Result of comparing baseline (no model) vs model-assisted runs."""

    baseline: Report
    model: Report
    deltas: list[CaseDelta]

    @property
    def baseline_rate(self) -> float:
        return self.baseline.pass_rate

    @property
    def model_rate(self) -> float:
        return self.model.pass_rate

    @property
    def improved(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.improved]

    @property
    def regressed(self) -> list[CaseDelta]:
        return [d for d in self.deltas if d.regressed]

    @property
    def net_gain(self) -> float:
        return self.model_rate - self.baseline_rate


class ModelComparison:
    """Runs the same benchmark twice: no-model baseline vs model-assisted.

    Reuses the existing Evaluator verbatim; the only difference between the
    two runs is whether the per-case planner is given a ModelProvider.
    """

    def __init__(self, memory: MemoryStore, workspace_root: str) -> None:
        self._memory = memory
        self._root = workspace_root

    def run(
        self,
        model: ModelProvider,
        cases: list[EvalCase] | None = None,
    ) -> Comparison:
        cases = cases if cases is not None else default_suite()

        # Baseline: evaluator with NO model (today's behavior).
        baseline = Evaluator(self._memory, self._root, model=None).run(cases)

        # Candidate: evaluator whose per-case planner is model-assisted.
        candidate = Evaluator(self._memory, self._root, model=model).run(cases)

        by_name = {r.name: r for r in baseline.results}
        deltas = [
            CaseDelta(
                name=r.name,
                baseline_passed=by_name[r.name].passed,
                model_passed=r.passed,
            )
            for r in candidate.results
        ]

        comp = Comparison(baseline=baseline, model=candidate, deltas=deltas)
        self._memory.record(
            "model_comparison",
            {
                "baseline_rate": round(comp.baseline_rate, 4),
                "model_rate": round(comp.model_rate, 4),
                "net_gain": round(comp.net_gain, 4),
                "improved": [d.name for d in comp.improved],
                "regressed": [d.name for d in comp.regressed],
            },
        )
        return comp


# ---------------------------------------------------------------------------
# Skill-specific result types
# ---------------------------------------------------------------------------

@dataclass
class SkillCaseResult:
    """Outcome for a single workflow case in one mode (skill on or off)."""
    name: str
    completed: bool
    retries: int = 0
    repairs: int = 0
    blocked: int = 0


@dataclass
class SkillComparisonResult:
    """Two-mode comparison: no-skill (off) vs skill-enabled (on).

    Reuses the same workflow suite; the only difference is whether a
    SkillRegistry with the candidate skill is wired into the planner.
    Metrics: completion rate, retries, repairs, blocked attempts.
    """
    baseline: list[SkillCaseResult] = field(default_factory=list)
    candidate: list[SkillCaseResult] = field(default_factory=list)

    @property
    def completion_off(self) -> float:
        if not self.baseline:
            return 0.0
        return sum(1 for r in self.baseline if r.completed) / len(self.baseline)

    @property
    def completion_on(self) -> float:
        if not self.candidate:
            return 0.0
        return sum(1 for r in self.candidate if r.completed) / len(self.candidate)

    @property
    def regressed(self) -> list[str]:
        by_name = {r.name: r for r in self.baseline}
        return [
            r.name for r in self.candidate
            if r.name in by_name and by_name[r.name].completed and not r.completed
        ]

    @property
    def blocked_off(self) -> int:
        return sum(r.blocked for r in self.baseline)

    @property
    def blocked_on(self) -> int:
        return sum(r.blocked for r in self.candidate)

    @property
    def total_retries_off(self) -> int:
        return sum(r.retries for r in self.baseline)

    @property
    def total_retries_on(self) -> int:
        return sum(r.retries for r in self.candidate)

    @property
    def total_repairs_off(self) -> int:
        return sum(r.repairs for r in self.baseline)

    @property
    def total_repairs_on(self) -> int:
        return sum(r.repairs for r in self.candidate)

    @property
    def accepted(self) -> bool:
        if self.completion_on < self.completion_off:
            return False
        if self.regressed:
            return False
        if self.blocked_on > self.blocked_off:
            return False
        if self.completion_on > self.completion_off:
            return True
        if self.total_retries_on < self.total_retries_off:
            return True
        if self.total_repairs_on < self.total_repairs_off:
            return True
        if self.completion_on == self.completion_off:
            return True
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_fn(arg: str) -> str:
    data = json.loads(arg)
    Path(data["path"]).write_text(data["content"], encoding="utf-8")
    return f"wrote {data['path']}"


def _run_workflow_case(
    case: WorkflowCase,
    root: str,
    memory: MemoryStore,
    skills: SkillRegistry | None,
) -> SkillCaseResult:
    """Run one workflow case through the full executive path and collect metrics."""
    # Write fixtures.
    for rel, content in case.fixtures.items():
        Path(root, rel).parent.mkdir(parents=True, exist_ok=True)
        Path(root, rel).write_text(content, encoding="utf-8")

    safe_mode = case.safe_mode
    mem = MemoryStore(str(Path(root) / "wf_events.jsonl"))
    queue = TaskQueue(str(Path(root) / "wf_queue.jsonl"), mem)
    config = Config(
        log_path=str(Path(root) / "wf_ctrl.jsonl"),
        workspace_root=root,
        safe_mode=safe_mode,
        reflection_enabled=True,
    )
    plan_store = PlanStore(str(Path(root) / "wf_plans"))

    tool_reg = ToolRegistry()
    tool_reg.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    tool_reg.register(Tool(name="read_file", description="read",
                           run=lambda a: Path(json.loads(a)["path"]).read_text(), safe=True))
    tool_reg.register(Tool(name="list_dir", description="list",
                           run=lambda a: "\n".join(
                               sorted(p.name for p in Path(json.loads(a)["path"]).iterdir())
                           ), safe=True))
    tool_reg.register(Tool(name="write_file", description="write",
                           run=_write_fn, safe=not safe_mode))

    ctrl_mem = MemoryStore(str(Path(root) / "wf_ctrl_mem.jsonl"))
    safety = SafetyLayer(ctrl_mem, safe_mode=safe_mode,
                         rules=build_default_rules(root))
    planner = Planner(
        registry_tools=tuple(tool_reg.list()),
        skills=skills,
    )
    controller = Controller(config, registry=tool_reg, memory=ctrl_mem,
                            safety=safety, planner=planner)

    from ..controller.executive import ExecutiveController
    executive = ExecutiveController(config, queue, mem, controller=controller,
                                    max_retries=3, plan_store=plan_store)

    rec = queue.enqueue(case.task)
    for _ in range(20):
        state = queue.get(rec.id).state
        if state in (TaskState.DONE, TaskState.FAILED,
                     TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED):
            break
        executive.run_once()

    final_state = queue.get(rec.id).state
    completed = final_state == TaskState.DONE

    # Count metrics from memory journal.
    history = mem.history()
    kinds = [e["kind"] for e in history]
    retries = kinds.count("step_replan")
    repairs = kinds.count("repair_inserted")
    blocked = kinds.count("action_blocked")

    return SkillCaseResult(
        name=case.name,
        completed=completed,
        retries=retries,
        repairs=repairs,
        blocked=blocked,
    )


# ---------------------------------------------------------------------------
# Skill comparison
# ---------------------------------------------------------------------------

class SkillComparison:
    """Runs the same workflow suite twice: no-skill baseline vs skill-enabled.

    The only difference is whether the candidate skill is registered in the
    planner's SkillRegistry.  Every other component (SafetyLayer, Reflection,
    Executive, Memory) is identical.
    """

    def __init__(self, memory: MemoryStore, workspace_root: str) -> None:
        self._memory = memory
        self._root = workspace_root

    def run(
        self,
        cases: list[WorkflowCase],
        skill=None,  # SkillTemplate — avoid circular import
    ) -> SkillComparisonResult:
        baseline_results: list[SkillCaseResult] = []
        candidate_results: list[SkillCaseResult] = []

        for case in cases:
            # Baseline: no skill.
            baseline_results.append(
                _run_workflow_case(case, self._root, self._memory, skills=None)
            )

            # Candidate: skill registered (if the case specifies one).
            skill_reg = None
            if skill is not None and case.skill is not None:
                skill_reg = SkillRegistry(str(Path(self._root) / "candidate_skills.jsonl"))
                # Only register if the case's skill name matches.
                if skill.name == case.skill:
                    skill_reg.register(skill)

            candidate_results.append(
                _run_workflow_case(case, self._root, self._memory, skills=skill_reg)
            )

        comp = SkillComparisonResult(
            baseline=baseline_results,
            candidate=candidate_results,
        )
        self._memory.record(
            "skill_comparison",
            {
                "completion_off": round(comp.completion_off, 4),
                "completion_on": round(comp.completion_on, 4),
                "regressed": comp.regressed,
                "blocked_off": comp.blocked_off,
                "blocked_on": comp.blocked_on,
                "accepted": comp.accepted,
            },
        )
        return comp
