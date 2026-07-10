from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..memory.store import MemoryStore
from .cases import EvalCase, default_suite
from .evaluator import Evaluator, Report

if TYPE_CHECKING:
    from ..model import ModelProvider


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
