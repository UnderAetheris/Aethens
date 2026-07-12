"""Experience-Guided Retirement v0 — closing the learn→mine→promote→retire loop.

Promotion (mining + SkillComparison gate) already exists.  This milestone is
the *retire* half, driven by real-run evidence: a skill that the world keeps
proving unreliable gets quietly retired — bounded and reversible, never a hard
delete.

The same discipline as the prior milestones applies:

- **Consumption is gated.**  The retirer only ever reads ``experience.query()``,
  the exact same gated surface the Selection milestone used.  When consumption
  is off, ``query()`` returns ``[]`` and *nothing is retired* — which is what
  makes guided-off byte-identical to Experience v0 (the promotion-only loop).
- **Bounded.**  A skill is a retirement candidate only when the net experience
  bias against it crosses ``retire_bias_threshold`` — confidence-weighted, and
  net of any ``WORKED_WELL`` evidence.  A single weak or contradicted lesson
  cannot retire a skill; the avoidance has to be earned and sustained.  This is
  the "bounded" in bounded reversible retirement.
- **Reversible.**  Retirement is an append-only tombstone
  (``SkillRegistry.retire``); ``SkillRegistry.unretire`` re-activates it.  The
  retirer exposes ``restore`` so a retirement can always be walked back.
- **Read-only scan first.**  ``candidates_for_retirement`` observes without
  mutating, so callers (and tests) can inspect *what would retire* before any
  state changes.  Retirement never decides on its own; the owner enacts it.

The retirer deliberately carries no authority it didn't inherit: it reuses the
planner/renderer's already-enumerated, already-gated skill set and the shared
``experience_bias`` core.  Experience re-ranks *and* (now) can retire, but it
still never introduces an option.
"""
from __future__ import annotations

from typing import Any

from ..memory.experience_rerank import experience_bias


# Net avoid-evidence (in roughly [-1, 1]) at or below this triggers retirement.
# Tuned so a lone low-confidence failure (e.g. one 0.5 avoid lesson -> bias -0.5)
# does NOT retire, but sustained/confident avoidance does.
DEFAULT_RETIRE_BIAS_THRESHOLD = -0.6


def _skill_key(skill: Any) -> str:
    triggers = getattr(skill, "trigger_patterns", ()) or ()
    return f"{getattr(skill, 'name', '')} {' '.join(triggers)}"


class ExperienceGuidedRetirer:
    """Retire skills whose real-run evidence has turned against them.

    Bounded (confidence-weighted net bias threshold) and reversible
    (``SkillRegistry`` tombstone + ``unretire``).  Only acts on
    ``experience.query()`` output, so consumption-off retires nothing.
    """

    def __init__(
        self,
        experience: Any,
        *,
        retire_bias_threshold: float = DEFAULT_RETIRE_BIAS_THRESHOLD,
    ) -> None:
        self._experience = experience
        self._threshold = retire_bias_threshold

    # ------------------------------------------------------------------ #
    # Read-only observation (no mutation)                                 #
    # ------------------------------------------------------------------ #

    def candidates_for_retirement(self, registry: Any) -> list[tuple[str, str, float]]:
        """Active skills whose net experience bias <= threshold.

        Returns a list of ``(skill_id, reason, bias)`` — what *would* retire,
        without changing any state.  When consumption is off (``query() == []``)
        this is empty, so retirement is a no-op.
        """
        lessons = self._experience.query()
        if not lessons:
            return []
        out: list[tuple[str, str, float]] = []
        for skill in registry.active_skills():
            bias = experience_bias(_skill_key(skill), lessons)
            if bias <= self._threshold:
                out.append((
                    skill.id,
                    f"real-run evidence against '{skill.name}' (net bias {bias:.2f})",
                    bias,
                ))
        return out

    # ------------------------------------------------------------------ #
    # Enact (bounded + reversible)                                        #
    # ------------------------------------------------------------------ #

    def retire_stale(self, registry: Any, memory: Any | None = None) -> list[str]:
        """Retire the candidate skills. Returns the retired skill ids.

        Each retirement is an append-only tombstone (reversible via ``restore``
        or ``SkillRegistry.unretire``).  ``retire_stale`` with consumption off
        retires nothing and leaves the skill library byte-identical.
        """
        retired_ids: list[str] = []
        for skill_id, reason, _ in self.candidates_for_retirement(registry):
            if registry.retire(skill_id):
                retired_ids.append(skill_id)
                if memory is not None:
                    memory.record(
                        "skill_retired_experience",
                        {"skill_id": skill_id, "reason": reason},
                    )
        return retired_ids

    def restore(self, skill_id: str, registry: Any, memory: Any | None = None) -> bool:
        """Reverse a retirement (re-activate the skill). Returns True if restored."""
        ok = registry.unretire(skill_id)
        if ok and memory is not None:
            memory.record("skill_restored_experience", {"skill_id": skill_id})
        return ok
