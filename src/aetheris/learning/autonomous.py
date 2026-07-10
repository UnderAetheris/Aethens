"""Autonomous improvement loop: run when the system is idle, no user needed.

This is the "become better every second" engine.  When the executive's queue
is empty for long enough, this loop:
1. Runs the benchmark + keyword learning (existing LearningEngine).
2. Mines the plan journal for new skill candidates (AutoSkillSynthesizer).
3. Detects recurring failures and proposes repairs (SelfRepair).
4. Runs discovery experiments to expand known capabilities.

All mutations go through the existing safety + evaluation gates.  Nothing
bypasses the safety spine.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..evaluation.cases import default_suite
from ..learning.engine import LearningEngine
from ..learning.synthesis import AutoSkillSynthesizer
from ..memory.store import MemoryStore

if TYPE_CHECKING:
    from ..skills.registry import SkillRegistry


@dataclass
class CycleResult:
    """Outcome of one autonomous improvement cycle."""
    learned: bool
    learned_keyword: str | None = None
    skills_proposed: int = 0
    skills_promoted: int = 0
    repairs_proposed: int = 0
    repairs_applied: int = 0
    discoveries: int = 0
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class AutonomousLoop:
    """Runs improvement cycles when the system is idle.

    Wired into ExecutiveController as the improve_fn.  Each call runs one
    full cycle: learn, synthesize, repair, discover.
    """

    def __init__(
        self,
        memory: MemoryStore,
        workspace_root: str,
        knowledge,
        experience,
        learned,
        registry: SkillRegistry | None = None,
    ) -> None:
        self._memory = memory
        self._root = workspace_root
        self._knowledge = knowledge
        self._experience = experience
        self._learned = learned
        self._registry = registry

        self._engine = LearningEngine(
            memory, workspace_root, knowledge, experience, learned
        )
        self._synthesizer = (
            AutoSkillSynthesizer(memory, workspace_root, registry)
            if registry is not None
            else None
        )

        self.last_result: CycleResult | None = None
        self._total_cycles: int = 0
        self._started_at: float = time.time()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def cycle(self) -> CycleResult:
        """Run one full autonomous improvement cycle."""
        t0 = time.time()
        result = CycleResult(learned=False)
        self._total_cycles += 1

        # 1. Keyword learning.
        try:
            learning_result = self._engine.attempt(default_suite())
            if learning_result.accepted:
                result.learned = True
                result.learned_keyword = (
                    f"{learning_result.candidate.intent}:{learning_result.candidate.keyword}"
                    if learning_result.candidate
                    else None
                )
        except Exception as exc:
            result.errors.append(f"learning failed: {exc}")

        # 2. Auto-skill synthesis.
        if self._synthesizer is not None:
            try:
                synth = self._synthesizer.synthesize()
                result.skills_proposed = len(synth.proposed)
                result.skills_promoted = len(synth.promoted)
                result.errors.extend(synth.errors)
            except Exception as exc:
                result.errors.append(f"synthesis failed: {exc}")

        # 3. Self-repair (lightweight: detect recurring failures).
        try:
            repairs = self._detect_recurring_failures()
            result.repairs_proposed = len(repairs)
            for repair in repairs:
                if self._apply_repair(repair):
                    result.repairs_applied += 1
        except Exception as exc:
            result.errors.append(f"repair failed: {exc}")

        # 4. Discovery (placeholder for future expansion).
        try:
            result.discoveries = self._run_discovery()
        except Exception as exc:
            result.errors.append(f"discovery failed: {exc}")

        result.duration_ms = (time.time() - t0) * 1000
        self.last_result = result
        return result

    @property
    def total_cycles(self) -> int:
        return self._total_cycles

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    # ------------------------------------------------------------------ #
    # Self-repair                                                         #
    # ------------------------------------------------------------------ #

    def _detect_recurring_failures(self) -> list[dict[str, Any]]:
        """Scan memory for failure patterns that repeat often enough to fix.

        Returns a list of repair proposals (each a dict with problem/cause/fix).
        """
        history = self._memory.history()
        failures: list[str] = []
        for entry in history:
            if entry.get("kind") in (
                "task_blocked",
                "step_blocked",
                "step_replan",
                "repair_inserted",
            ):
                detail = entry.get("data", {}).get("reason", "") or entry.get("detail", "")
                if detail:
                    failures.append(detail)

        # Count occurrences.
        counter: dict[str, int] = {}
        for f in failures:
            counter[f] = counter.get(f, 0) + 1

        threshold = 3
        return [
            {"problem": reason, "cause": reason, "fix": "auto: see memory", "count": count}
            for reason, count in counter.items()
            if count >= threshold
        ]

    def _apply_repair(self, repair: dict[str, Any]) -> bool:
        """Record a repair proposal in the experience store.

        Actual code mutation is deferred to a human-approved path.
        """
        try:
            self._experience.add(
                problem=repair.get("problem", ""),
                cause=repair.get("cause", ""),
                fix=repair.get("fix", ""),
                evidence=f"recurring failure (count={repair.get('count', 0)})",
                confidence=0.3,
            )
            self._memory.record(
                "self_repair_proposed",
                {"problem": repair.get("problem", ""), "count": repair.get("count", 0)},
            )
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Discovery                                                            #
    # ------------------------------------------------------------------ #

    def _run_discovery(self) -> int:
        """Probe for new capabilities by running a lightweight exploration.

        In this version discovery is a no-op; future versions will:
        - Generate novel task phrasings
        - Test them through the controller
        - Record what works and what doesn't
        - Feed successes into the synthesis pipeline
        """
        return 0
