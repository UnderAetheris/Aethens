"""Experience-Guided Skill Selection v0 — the shared re-ranker.

The whole milestone rests on one principle, and it is what keeps authority
from widening: **experience re-ranks existing options; it never introduces
one.**  The planner, the renderer, Reflection, and Learning already enumerate
the valid choices today.  Experience only biases the *preference order*
toward what ``WORKED_WELL`` in this context and away from what
``FAILED_REPEATEDLY``.  The option set is unchanged, every option is still
gated, only the order shifts — and only when a confident lesson exists.

This module is the single shared core all three selection seams use, so the
behavior is consistent and testable in one place.  It is stable and
conservative by design:

- Options without a confident lesson keep their base order.  No lesson ->
  original order -> byte-identical fallback.
- ``experience_rerank`` returns a *permutation of the same list*.  It never
  appends or removes an option, so the authority surface is identical.
- The honest ``[]`` that ExperienceMemory returns when consumption is off is
  exactly the mechanism that makes the floor equal to today's deterministic
  selection.  No downside risk, which is what lets the gate read
  "help or neutral," never "help at the cost of a regression."

Integration:
- Planner/renderer skill selection -> ``SkillRegistry.match`` re-ranks by
  ``experience_rerank``.
- Reasoning -> experience enters only as ``Observation`` rows with
  ``Provenance(source="experience")``; abstention still governs thin history
  exactly as thin evidence (no schema change).
- Learning -> experience can only make the gate *more* conservative (a reason
  to HOLD); it never hands Learning a reason to adopt something the measured
  gate rejects.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from .lessons import Lesson

# A skill/option gets a stable, readable comparison key from these callables.
KeyFn = Callable[[Any], str]


def _lesson_text(les: Lesson) -> str:
    return f"{les.problem} {les.cause} {les.fix}".lower()


def _significant_tokens(text: str) -> set[str]:
    """Deterministic overlap test: 4+ char lowercased tokens only.

    Short tokens (a, an, the, fix, ...) are too noisy to associate a lesson
    with an option, so they are excluded.  Empty input -> no overlaps.
    """
    return {t for t in text.lower().split() if len(t) >= 4}


def _lesson_relevant(key: str, les: Lesson) -> bool:
    """True if a lesson plausibly bears on this option key.

    Conservatively requires at least one significant token shared between the
    option's key and the lesson's problem/cause/fix.  This keeps experience
    from bleeding onto unrelated options (which would be the "leak" the
    canary guards against).
    """
    key_tokens = _significant_tokens(key)
    if not key_tokens:
        return False
    return not key_tokens.isdisjoint(_significant_tokens(_lesson_text(les)))


def experience_bias(key: str, lessons: Sequence[Lesson]) -> float:
    """Net preference for an option key, in roughly [-1, 1].

    WORKED_WELL / FAILED_AND_RECOVERED add ``+confidence``; FAILED_REPEATEDLY
    subtracts ``-confidence``; FAILED_SAFELY is a safety floor and contributes
    nothing (we never promote "it failed safely" as a technique to repeat).
    Only lessons relevant to ``key`` count.
    """
    bias = 0.0
    for les in lessons:
        if not _lesson_relevant(key, les):
            continue
        ot = les.outcome_type
        if ot.is_success:
            bias += les.confidence
        elif ot.is_avoid:
            bias -= les.confidence
        # FAILED_SAFELY -> neutral
    return bias


def experience_rerank(
    options: Sequence[Any],
    lessons: Sequence[Lesson],
    *,
    keyfn: KeyFn = str,
) -> list[Any]:
    """Re-rank an existing ordered list of options by experience.

    The list is a *permutation of the input* — no option is added or removed.
    Options are sorted by descending bias; ties (including bias == 0, the
    no-lesson case) preserve the original relative order (Python's sort is
    stable), which is what makes guided-off byte-identical to guided-on-with-
    no-confident-lessons.

    Args:
        options: the already-valid option list (skills, shapes, approaches…).
        lessons: confident lessons from ``ExperienceMemory.query()`` (an empty
            sequence is the honest ``[]`` that yields the base order).
        keyfn: maps an option to a comparison string (skill name+triggers,
            shape steps, candidate id…).
    """
    if not lessons:
        return list(options)  # honest empty -> byte-identical fallback

    ranked = sorted(
        options,
        key=lambda o: -round(experience_bias(keyfn(o), lessons), 6),
    )
    return ranked
