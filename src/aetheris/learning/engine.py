from __future__ import annotations

from dataclasses import dataclass

from ..evaluation.cases import EvalCase
from ..evaluation.evaluator import Evaluator
from ..memory.experience import ExperienceStore
from ..memory.experience_rerank import experience_bias
from ..memory.knowledge import KnowledgeStore
from ..memory.learned import LearnedKeywordStore, LearnedStep
from ..memory.store import MemoryStore


_TOOL_TO_INTENT = {"write_file": "write", "read_file": "read", "list_dir": "list"}


@dataclass(frozen=True)
class Candidate:
    """Exactly one bounded change: teach an intent one new keyword."""

    intent: str
    keyword: str
    from_case: str


@dataclass
class LearningResult:
    accepted: bool
    reason: str
    baseline_rate: float
    new_rate: float
    candidate: Candidate | None


class LearningEngine:
    """Smallest safe self-improvement loop.

    detect failures -> record experience -> propose ONE bounded rule ->
    test via evaluator -> accept iff strictly better and no regressions,
    else roll back. Reversible because the only lever is the planner's
    extra_keywords map, which lives in memory, not in source.
    """

    def __init__(
        self,
        memory: MemoryStore,
        workspace_root: str,
        knowledge: KnowledgeStore,
        experience: ExperienceStore,
        learned: LearnedKeywordStore,
        experience_lessons=None,
    ) -> None:
        self._memory = memory
        self._root = workspace_root
        self._knowledge = knowledge
        self._experience = experience
        self._learned = learned
        self._experience_lessons = experience_lessons  # ExperienceMemory | None
        self.extra_keywords: dict[str, list[str]] = self._learned.as_keywords()
        self.last_result: LearningResult | None = None

    def failing_cases(self, cases: list[EvalCase]) -> list[EvalCase]:
        evaluator = Evaluator(self._memory, self._root, self.extra_keywords)
        report = evaluator.run(cases)
        failed_names = {r.name for r in report.results if not r.passed}
        return [c for c in cases if c.name in failed_names]

    def propose_one(self, cases: list[EvalCase]) -> Candidate | None:
        for case in self.failing_cases(cases):
            intent = _TOOL_TO_INTENT.get(case.expected_tool or "")
            if not intent:
                continue
            keyword = self._keyword_from_task(case.task)
            if not keyword:
                continue
            self._experience.add(
                problem=f"eval case '{case.name}' planned wrong tool",
                cause=f"planner lacked a keyword mapping '{keyword}' -> {intent}",
                fix=f"add extra keyword '{keyword}' for intent '{intent}'",
                evidence=f"task={case.task!r} expected_tool={case.expected_tool}",
                related_eval_case=case.name,
                confidence=0.4,
            )
            return Candidate(intent=intent, keyword=keyword, from_case=case.name)
        return None

    def _keyword_from_task(self, task: str) -> str | None:
        for tok in task.lower().split():
            word = "".join(ch for ch in tok if ch.isalpha())
            if len(word) >= 3:
                return word
        return None

    def attempt(self, cases: list[EvalCase]) -> LearningResult:
        baseline = Evaluator(self._memory, self._root, dict(self.extra_keywords)).run(cases)
        candidate = self.propose_one(cases)

        # Experience can only make the gate MORE conservative.  A confident
        # real-run FAILED_REPEATEDLY lesson that bears on this candidate's
        # intent/keyword is a reason to HOLD — never a reason to adopt.  The
        # measured gate remains the sole adopter; experience never promotes
        # something the gate would reject.
        if candidate is not None and self._experience_lessons is not None:
            bias = experience_bias(
                f"{candidate.intent} {candidate.keyword}",
                self._experience_lessons.query(),
            )
            if bias < 0:
                self._memory.record(
                    "learning_held_experience",
                    {
                        "intent": candidate.intent,
                        "keyword": candidate.keyword,
                        "from_case": candidate.from_case,
                        "reason": "confident real-run failure on this intent/keyword",
                    },
                )
                result = LearningResult(
                    accepted=False,
                    reason="experience hold: confident real-run failure on this intent/keyword",
                    baseline_rate=baseline.pass_rate,
                    new_rate=baseline.pass_rate,
                    candidate=candidate,
                )
                self.last_result = result
                return result

        if candidate is None:
            result = LearningResult(
                accepted=False,
                reason="no bounded candidate available",
                baseline_rate=baseline.pass_rate,
                new_rate=baseline.pass_rate,
                candidate=None,
            )
            self.last_result = result
            return result

        trial = {k: list(v) for k, v in self.extra_keywords.items()}
        trial.setdefault(candidate.intent, [])
        if candidate.keyword not in trial[candidate.intent]:
            trial[candidate.intent].append(candidate.keyword)

        self._memory.record(
            "learning_attempt",
            {
                "intent": candidate.intent,
                "keyword": candidate.keyword,
                "from_case": candidate.from_case,
                "baseline_rate": baseline.pass_rate,
            },
        )

        trial_report = Evaluator(self._memory, self._root, trial).run(cases)

        baseline_pass = {r.name for r in baseline.results if r.passed}
        trial_fail = {r.name for r in trial_report.results if not r.passed}
        regressed = baseline_pass & trial_fail
        improved = trial_report.pass_rate > baseline.pass_rate

        if improved and not regressed:
            self._learned.append(candidate.intent, candidate.keyword, candidate.from_case)
            self.extra_keywords = self._learned.as_keywords()
            self._knowledge.add(
                title=f"planner keyword '{candidate.keyword}' -> {candidate.intent}",
                source=f"learning:{candidate.from_case}",
                summary=f"Learned that '{candidate.keyword}' signals {candidate.intent} intent.",
                tags=["planner", "learned"],
                confidence=0.7,
            )
            self._memory.record(
                "learning_accepted",
                {
                    "intent": candidate.intent,
                    "keyword": candidate.keyword,
                    "new_rate": trial_report.pass_rate,
                },
            )
            result = LearningResult(
                accepted=True,
                reason="strict improvement, no regressions",
                baseline_rate=baseline.pass_rate,
                new_rate=trial_report.pass_rate,
                candidate=candidate,
            )
            self.last_result = result
            return result

        reason = (
            "regression detected"
            if regressed
            else "no improvement (inconclusive or worse)"
        )
        self._memory.record(
            "learning_rejected",
            {
                "intent": candidate.intent,
                "keyword": candidate.keyword,
                "new_rate": trial_report.pass_rate,
                "reason": reason,
            },
        )
        result = LearningResult(
            accepted=False,
            reason=reason,
            baseline_rate=baseline.pass_rate,
            new_rate=trial_report.pass_rate,
            candidate=candidate,
        )
        self.last_result = result
        return result

    def revert_last(self) -> LearnedStep | None:
        removed = self._learned.revert_last()
        self.extra_keywords = self._learned.as_keywords()
        if removed is None:
            self._memory.record("learning_revert_noop", {"reason": "no accepted steps"})
            return None
        self._memory.record(
            "learning_reverted",
            {
                "intent": removed.intent,
                "keyword": removed.keyword,
                "from_case": removed.from_case,
            },
        )
        return removed

    # ------------------------------------------------------------------ #
    # Skill promotion / demotion                                          #
    # ------------------------------------------------------------------ #

    def promote_skill(
        self,
        skill,  # SkillTemplate — avoid circular import
        registry,  # SkillRegistry
        cases: list | None = None,
        workspace_root: str | None = None,
    ) -> bool:
        """Promote a skill candidate: register only if it clears the measured gate.

        Uses SkillComparison for WorkflowCase lists (same two-clause gate as
        hand-authored skills: completion >= baseline, no regressions,
        safety-neutral).  Falls back to an anchor-check for EvalCase lists
        (backward compatibility).
        """
        from ..evaluation.cases import ANCHOR_NAMES, WorkflowCase

        root = workspace_root or self._root

        if cases and all(isinstance(c, WorkflowCase) for c in cases):
            from ..evaluation.compare import SkillComparison
            comp = SkillComparison(self._memory, root)
            result = comp.run(cases, skill=skill)
            if not result.accepted:
                self._memory.record(
                    "skill_promotion_rejected",
                    {
                        "skill_name": skill.name,
                        "reason": (
                            f"gate not cleared: "
                            f"completion_on={result.completion_on:.2f} "
                            f"completion_off={result.completion_off:.2f} "
                            f"regressed={result.regressed}"
                        ),
                    },
                )
                return False
            registered = registry.register(skill)
            self._memory.record(
                "skill_promoted",
                {
                    "skill_id": registered.id,
                    "skill_name": registered.name,
                    "version": registered.version,
                    "completion_on": round(result.completion_on, 4),
                    "completion_off": round(result.completion_off, 4),
                    "regressed": result.regressed,
                },
            )
            return True

        if cases:
            from ..evaluation.evaluator import Evaluator
            baseline = Evaluator(self._memory, root, dict(self.extra_keywords)).run(cases)
            anchor_failures = [
                r for r in baseline.results
                if r.name in ANCHOR_NAMES and not r.passed
            ]
            if anchor_failures:
                self._memory.record(
                    "skill_promotion_rejected",
                    {"skill_name": skill.name, "reason": "anchor failures at baseline"},
                )
                return False

        registered = registry.register(skill)
        self._memory.record(
            "skill_promoted",
            {"skill_id": registered.id, "skill_name": registered.name,
             "version": registered.version},
        )
        return True

    def demote_skill(self, skill_id: str, registry, reason: str = "") -> bool:
        """Retire a skill (append-only tombstone). Returns True if found and retired."""
        retired = registry.retire(skill_id)
        if retired:
            self._memory.record(
                "skill_demoted",
                {"skill_id": skill_id, "reason": reason},
            )
        return retired
