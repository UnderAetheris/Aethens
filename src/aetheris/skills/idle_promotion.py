"""Idle-time skill promotion: bounded, cooperative wrapper the Executive
calls when idle.  Reuses SkillPromoter + try_promote verbatim; adds only
budget control, preemption on work arrival, and skip-already-active logic.

Default-off: pass None to ExecutiveController to get byte-identical-to-today.
"""
from __future__ import annotations

from typing import Callable

from ..skills.promoter import render_candidate, valid_dag, candidate_to_template


class IdleSkillPromotion:
    """Thin wrapper the Executive calls during idle windows.

    Responsibilities:
    - mine(): read-only, returns untried candidates from the journal.
    - try_one(candidate): render -> DAG -> SkillComparison gate ->
      LearningEngine.promote_skill; journals accept/reject with provenance.
    - Tracks mined/tried/promoted/rejected counts for observability.
    """

    def __init__(
        self,
        promoter,  # SkillPromoter
        registry,  # SkillRegistry
        learning,  # LearningEngine
        comparison,  # SkillComparison
        memory,  # MemoryStore
        workspace_root: str,
        history_provider: Callable[[], list],
        promotion_budget: int = 1,
    ) -> None:
        self._promoter = promoter
        self._registry = registry
        self._learning = learning
        self._comparison = comparison
        self._memory = memory
        self._root = workspace_root
        self._history = history_provider
        self._budget = promotion_budget

        # Observability counters.
        self.mined: int = 0
        self.tried: int = 0
        self.promoted_names: list[str] = []
        self.rejected_names: list[str] = []

    def mine(self) -> list:
        """Read-only: return untried candidates from the plan journal.

        Skips shapes whose name already backs an active skill.
        """
        completed = self._history()
        candidates = self._promoter.candidates(completed, memory=self._memory)
        active_names = {s.name for s in self._registry.active_skills()}
        untried = [c for c in candidates if c.name not in active_names]
        self.mined = len(untried)
        return untried

    def try_one(self, candidate) -> bool:
        """Render -> DAG -> SkillComparison gate -> promote/reject.

        Returns True if accepted, False if rejected.
        """
        from ..evaluation.cases import skill_workflow_suite

        self._memory.record("skill_candidate_mined", {
            "name": candidate.name,
            "provenance": candidate.provenance,
        })

        rendered = render_candidate(candidate, f"idle-{candidate.name}")
        if rendered is None or not valid_dag(rendered):
            self.rejected_names.append(candidate.name)
            self._memory.record("skill_promotion_rejected", {
                "skill_name": candidate.name,
                "reason": "invalid render or DAG",
            })
            self.tried += 1
            return False

        template = candidate_to_template(candidate)
        suite = skill_workflow_suite(self._root)
        result = self._comparison.run(suite, skill=template)

        if result.accepted:
            self._learning.promote_skill(template, self._registry, workspace_root=self._root)
            self.promoted_names.append(candidate.name)
        else:
            self._memory.record("skill_promotion_rejected", {
                "skill_name": candidate.name,
                "reason": (
                    f"gate not cleared: "
                    f"completion_on={result.completion_on:.2f} "
                    f"completion_off={result.completion_off:.2f} "
                    f"regressed={result.regressed}"
                ),
            })
            self.rejected_names.append(candidate.name)

        self.tried += 1
        return result.accepted
