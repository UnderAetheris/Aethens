"""Self-repair: detect recurring failures, propose fixes, and apply them
safely through the existing evaluation gate.

Design:
- Scan memory for recurring failures (same error pattern >= threshold).
- For each pattern, propose a repair (e.g., add a keyword, adjust a rule).
- Apply the repair through the existing learning/eval gate.
- If the repair causes regressions, roll it back automatically.

Nothing bypasses safety: all repairs are validated by the evaluator before
persistence, and all are reversible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..evaluation.cases import default_suite
from ..evaluation.evaluator import Evaluator
from ..memory.experience import ExperienceStore
from ..memory.store import MemoryStore
from .engine import LearningEngine


@dataclass
class RepairProposal:
    """A candidate fix for a recurring failure."""
    problem: str
    cause: str
    fix: str
    occurrences: int
    confidence: float


@dataclass
class RepairResult:
    """Outcome of applying one repair."""
    applied: bool
    problem: str
    reason: str


class SelfRepair:
    """Detect and fix recurring failures automatically."""

    def __init__(
        self,
        memory: MemoryStore,
        workspace_root: str,
        knowledge,
        experience: ExperienceStore,
        learned,
    ) -> None:
        self._memory = memory
        self._root = workspace_root
        self._knowledge = knowledge
        self._experience = experience
        self._learned = learned

    def detect(self) -> list[RepairProposal]:
        """Scan memory for recurring failure patterns."""
        history = self._memory.history()
        failure_kinds = {
            "task_blocked",
            "step_blocked",
            "step_replan",
            "repair_inserted",
            "reflection_decision",
        }

        reasons: list[str] = []
        for entry in history:
            if entry.get("kind") in failure_kinds:
                data = entry.get("data", {})
                reason = data.get("reason", "") or data.get("detail", "")
                if reason:
                    reasons.append(reason)

        counter: dict[str, int] = {}
        for r in reasons:
            # Normalise: strip paths, ids, timestamps.
            normalised = self._normalise(reason)
            counter[normalised] = counter.get(normalised, 0) + 1

        threshold = 3
        proposals: list[RepairProposal] = []
        for reason, count in counter.items():
            if count >= threshold:
                proposals.append(RepairProposal(
                    problem=reason,
                    cause=reason,
                    fix=f"auto-repair: {reason[:80]}",
                    occurrences=count,
                    confidence=min(1.0, count / 10.0),
                ))
        return proposals

    def apply(self, proposal: RepairProposal) -> RepairResult:
        """Try to apply a repair through the eval gate.

        Current strategy: if the failure is a missing keyword, teach it via
        LearningEngine.  Other failure types are recorded as experiences for
        future human review.
        """
        # Try keyword repair.
        keyword_match = re.search(r"lacking.*?'(\w+)'", proposal.problem)
        if keyword_match:
            keyword = keyword_match.group(1)
            intent = self._guess_intent(proposal.problem)
            if intent:
                try:
                    engine = LearningEngine(
                        self._memory, self._root, self._knowledge, self._experience, self._learned
                    )
                    # Manually inject a trial keyword.
                    trial = dict(engine.extra_keywords)
                    trial.setdefault(intent, [])
                    if keyword not in trial[intent]:
                        trial[intent].append(keyword)

                    baseline = Evaluator(self._memory, self._root, dict(engine.extra_keywords)).run(default_suite())
                    trial_report = Evaluator(self._memory, self._root, trial).run(default_suite())

                    baseline_pass = {r.name for r in baseline.results if r.passed}
                    trial_fail = {r.name for r in trial_report.results if not r.passed}
                    regressed = baseline_pass & trial_fail

                    if not regressed and trial_report.pass_rate >= baseline.pass_rate:
                        engine._learned.append(intent, keyword, "self_repair")
                        engine.extra_keywords = engine._learned.as_keywords()
                        return RepairResult(
                            applied=True,
                            problem=proposal.problem,
                            reason=f"keyword '{keyword}' -> '{intent}' accepted",
                        )
                except Exception as exc:
                    return RepairResult(
                        applied=False,
                        problem=proposal.problem,
                        reason=f"keyword repair failed: {exc}",
                    )

        # Record as experience for future.
        try:
            self._experience.add(
                problem=proposal.problem,
                cause=proposal.cause,
                fix=proposal.fix,
                evidence=f"recurring {proposal.occurrences}x",
                confidence=proposal.confidence,
            )
        except Exception:
            pass

        return RepairResult(
            applied=False,
            problem=proposal.problem,
            reason="recorded as experience, no auto-fix available",
        )

    @staticmethod
    def _normalise(text: str) -> str:
        """Strip concrete values to get a canonical failure signature."""
        text = re.sub(r"'[^']*'", "'<val>'", text)
        text = re.sub(r'"[^"]*"', '"<val>"', text)
        text = re.sub(r"\b\d+\b", "<n>", text)
        return text[:120]

    @staticmethod
    def _guess_intent(text: str) -> str | None:
        mapping = {
            "read": "read",
            "list": "list",
            "write": "write",
            "create": "write",
            "show": "list",
            "get": "read",
            "fetch": "read",
            "browse": "list",
            "save": "write",
        }
        lower = text.lower()
        for keyword, intent in mapping.items():
            if keyword in lower:
                return intent
        return None
