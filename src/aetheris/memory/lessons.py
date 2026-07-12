"""Experience Memory Engine v0 — the *provenance-stamped* record of what happened.

This module *formalizes and deepens* the existing problem/cause/fix
Experience store.  Understanding (aetheris.understanding) knows what the
code *is*; Experience knows what *happened when you touched it*.  One is
regenerable from source, the other is the provenance-stamped record of real
attempts.  Both are read-only advisory substrates.  Neither decides or acts.

Two design choices drive the whole file:

1. **The write path is split from the consume path, and only consumption is
   gated.**  Recording is a side-effect of the executive's normal run finishing
   — it *observes* the outcome, adds no step, no gate, no decision.  So
   recording is safe to turn on immediately.  The only thing that is
   default-off and benchmarked is *consuming* lessons, exposed through the
   `ExperienceMemory` facade: when consume is disabled it returns an honest
   empty list, and the caller takes its deterministic fallback.  Zero downside.

2. **The four `OutcomeType`s do real work.**  Distinguishing "worked well" /
   "failed safely" / "failed and recovered" / "failed repeatedly" is what lets
   a lesson say *"this repair reliably recovers this failure kind"* versus
   *"this approach keeps dying, avoid it."*  That is the difference between
   memory that compounds successes and memory that just hoards logs.

Guardrails:
- Consumers get read-only queries behind a confidence floor.  No confident
  lesson -> honest empty -> deterministic fallback.  Never acts.
- Lessons are bounded, expiring, and *reversibly* retired: a stale or
  contradicted lesson decays and retires, and `unretire` restores it exactly
  (the whole file is rewritten, so the operation is fully reversible).
- The `Lesson` schema has **no action field**.  It records what happened; it
  never carries or implies a directive.
- With consumption off, the substrate is byte-identical to Repo-Aware Skills
  v0: recording only appends to its own lessons file and never touches the
  decision path.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .jsonl import JsonlStore, make_id


class OutcomeType(str, Enum):
    """What happened when an attempt touched the system.

    The distinction is what makes a lesson actionable *as advice*:
    - WORKED_WELL:            the attempt succeeded cleanly.
    - FAILED_SAFELY:          it failed but inside the safety envelope
                              (blocked / denied), no blast radius.
    - FAILED_AND_RECOVERED:   it failed, then an inserted repair recovered it.
    - FAILED_REPEATEDLY:      it failed again and again and was abandoned.

    Lessons about WORKED_WELL / FAILED_AND_RECOVERED compound: they say
    "this reliably works."  Lessons about FAILED_REPEATEDLY say "avoid this."
    FAILED_SAFELY is recorded but never promoted (safety is the floor, not a
    technique to repeat).
    """

    WORKED_WELL = "worked_well"
    FAILED_SAFELY = "failed_safely"
    FAILED_AND_RECOVERED = "failed_and_recovered"
    FAILED_REPEATEDLY = "failed_repeatedly"

    @property
    def is_success(self) -> bool:
        """True for outcomes worth compounding (reliable, not just safe)."""
        return self in (OutcomeType.WORKED_WELL, OutcomeType.FAILED_AND_RECOVERED)

    @property
    def is_avoid(self) -> bool:
        """True for outcomes worth steering *away* from."""
        return self == OutcomeType.FAILED_REPEATEDLY


# ---------------------------------------------------------------------------
# Decay / expiry tuning (all deterministic, no randomness)
# ---------------------------------------------------------------------------

DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days without confirmation -> stale
DECAY_STEP = 0.2                          # confidence lost per contradiction
CONTRADICTION_RETIRE_AT = 4               # confirmed contradictions -> auto-retire
RETIRE_CONFIDENCE_FLOOR = 0.15            # confidence below this -> decayed out
MIN_CONFIDENCE_FLOOR = 0.2                # consumer confidence floor default
CONFIRM_CONFIDENCE_GAIN = 0.05            # small, bounded bump per confirmation


@dataclass
class Lesson:
    """A provenance-stamped record of what happened on a real attempt.

    No action field.  Advisory only.  `related_*` links it back to the task
    and eval case it was observed on so consumers can scope queries.
    """

    id: str
    outcome: str                       # OutcomeType value
    problem: str
    cause: str
    fix: str
    evidence: str = ""
    related_task: str | None = None
    related_eval_case: str | None = None
    confidence: float = 0.5
    created_at: float = 0.0
    last_confirmed_at: float = 0.0
    confirmations: int = 0
    contradictions: int = 0
    retired: bool = False
    retired_at: float | None = None
    retired_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Lesson":
        # Tolerate older records that lack newer fields.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def outcome_type(self) -> OutcomeType:
        return OutcomeType(self.outcome)


class LessonStore:
    """Typed, append-and-rewrite store for Lesson records.

    Append-only for normal recording (cheap, order-preserving).  State-changing
    operations (confirm / contradict / retire / unretire) rewrite the whole file
    so they are fully reversible via `unretire` / `restore`.
    """

    def __init__(self, path: str) -> None:
        self._store = JsonlStore(path)

    # ---- recording (write path) ------------------------------------------ #

    def add(
        self,
        outcome: OutcomeType,
        problem: str,
        cause: str,
        fix: str,
        evidence: str = "",
        related_task: str | None = None,
        related_eval_case: str | None = None,
        confidence: float = 0.5,
        now: float | None = None,
    ) -> Lesson:
        at = now if now is not None else time.time()
        lesson = Lesson(
            id=make_id("les", self._store.count() + 1, problem + fix),
            outcome=outcome.value,
            problem=problem,
            cause=cause,
            fix=fix,
            evidence=evidence,
            related_task=related_task,
            related_eval_case=related_eval_case,
            confidence=confidence,
            created_at=at,
            last_confirmed_at=at,
        )
        self._store.append(lesson.to_dict())
        return lesson

    # ---- reading (read-only queries) ------------------------------------ #

    def all(self) -> list[Lesson]:
        return [Lesson.from_dict(d) for d in self._store.all()]

    def get(self, lesson_id: str) -> Lesson | None:
        for d in self._store.all():
            if d.get("id") == lesson_id:
                return Lesson.from_dict(d)
        return None

    def query(
        self,
        problem: str | None = None,
        outcome: OutcomeType | None = None,
        min_confidence: float = 0.0,
        only_active: bool = True,
    ) -> list[Lesson]:
        """Read-only, deterministic filter.

        Never mutates.  Returns lessons matching the (optional) problem
        substring and outcome type, above `min_confidence`, optionally limited
        to non-retired lessons.  Deterministic order: file order.
        """
        rows = self._store.search(
            query=problem, fields=("problem", "cause", "fix", "evidence")
        )
        out: list[Lesson] = []
        for d in rows:
            lesson = Lesson.from_dict(d)
            if only_active and lesson.retired:
                continue
            if outcome is not None and lesson.outcome != outcome.value:
                continue
            if lesson.confidence < min_confidence:
                continue
            out.append(lesson)
        return out

    # ---- state change + decay (reversible via rewrite) ------------------- #

    def _persist(self, lessons: list[Lesson]) -> None:
        self._store.rewrite([les.to_dict() for les in lessons])

    def confirm(self, lesson_id: str, now: float | None = None) -> Lesson | None:
        lessons = self.all()
        for les in lessons:
            if les.id == lesson_id and not les.retired:
                les.confirmations += 1
                les.last_confirmed_at = now if now is not None else time.time()
                les.confidence = min(1.0, les.confidence + CONFIRM_CONFIDENCE_GAIN)
                self._persist(lessons)
                return les
        return None

    def contradict(self, lesson_id: str, now: float | None = None) -> Lesson | None:
        lessons = self.all()
        for les in lessons:
            if les.id == lesson_id and not les.retired:
                les.contradictions += 1
                les.confidence = max(0.0, les.confidence - DECAY_STEP)
                if (
                    les.confidence < RETIRE_CONFIDENCE_FLOOR
                    or les.contradictions >= CONTRADICTION_RETIRE_AT
                ):
                    les.retired = True
                    les.retired_at = now if now is not None else time.time()
                    les.retired_reason = "contradicted"
                self._persist(lessons)
                return les
        return None

    def retire(self, lesson_id: str, reason: str = "manual", now: float | None = None) -> Lesson | None:
        lessons = self.all()
        for les in lessons:
            if les.id == lesson_id and not les.retired:
                les.retired = True
                les.retired_at = now if now is not None else time.time()
                les.retired_reason = reason
                self._persist(lessons)
                return les
        return None

    def unretire(self, lesson_id: str) -> Lesson | None:
        lessons = self.all()
        for les in lessons:
            if les.id == lesson_id and les.retired:
                les.retired = False
                les.retired_at = None
                les.retired_reason = ""
                self._persist(lessons)
                return les
        return None

    def decay(self, now: float | None = None, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> list[Lesson]:
        """Retire stale lessons that have not been confirmed within the TTL.

        Deterministic: a lesson retired here is symmetrical with `retire` and
        fully reversible via `unretire`.  Returns the lessons retired this pass.
        """
        at = now if now is not None else time.time()
        lessons = self.all()
        retired_now: list[Lesson] = []
        changed = False
        for les in lessons:
            if les.retired:
                continue
            if at - les.last_confirmed_at > ttl_seconds and les.confirmations == 0:
                les.retired = True
                les.retired_at = at
                les.retired_reason = "expired"
                retired_now.append(les)
                changed = True
        if changed:
            self._persist(lessons)
        return retired_now


@dataclass
class _Null:
    pass


class ExperienceMemory:
    """Facade that *splits the write path from the consume path*.

    - `record(...)` writes a Lesson whenever the executive observes an outcome.
      It adds no step, no gate, no decision.  Turn it on immediately; it is
      harmless.  Gated by `record_enabled`.
    - `query(...)` / `advise(...)` are the *only* consume surface.  When
      `consume_enabled` is False (the default, and what benchmarks measure),
      they return an honest empty list so the caller takes its deterministic
      fallback.  Zero downside.  When enabled, they return read-only lessons
      above the confidence floor.
    """

    def __init__(
        self,
        path: str,
        *,
        record_enabled: bool = True,
        consume_enabled: bool = False,
        confidence_floor: float = MIN_CONFIDENCE_FLOOR,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._store = LessonStore(path)
        self._record_enabled = record_enabled
        self._consume_enabled = consume_enabled
        self._confidence_floor = confidence_floor
        self._ttl_seconds = ttl_seconds

    # ---- write path (always safe when enabled) --------------------------- #

    def record(
        self,
        outcome: OutcomeType,
        problem: str,
        cause: str,
        fix: str,
        evidence: str = "",
        related_task: str | None = None,
        related_eval_case: str | None = None,
        confidence: float = 0.5,
        now: float | None = None,
    ) -> Lesson | None:
        if not self._record_enabled:
            return None
        return self._store.add(
            outcome=outcome,
            problem=problem,
            cause=cause,
            fix=fix,
            evidence=evidence,
            related_task=related_task,
            related_eval_case=related_eval_case,
            confidence=confidence,
            now=now,
        )

    # ---- consume path (gated; honest-empty when off) -------------------- #

    def query(
        self,
        *,
        problem: str | None = None,
        outcome: OutcomeType | None = None,
        min_confidence: float | None = None,
    ) -> list[Lesson]:
        if not self._consume_enabled:
            return []  # gated: honest empty -> deterministic fallback
        floor = min_confidence if min_confidence is not None else self._confidence_floor
        return self._store.query(problem=problem, outcome=outcome, min_confidence=floor)

    def advise(self, problem: str | None = None) -> list[Lesson]:
        """Advisory-only read.  Callers may look but never act on this alone."""
        return self.query(problem=problem)

    def confirm(self, lesson_id: str, now: float | None = None) -> Lesson | None:
        return self._store.confirm(lesson_id, now=now)

    def contradict(self, lesson_id: str, now: float | None = None) -> Lesson | None:
        return self._store.contradict(lesson_id, now=now)

    def unretire(self, lesson_id: str) -> Lesson | None:
        return self._store.unretire(lesson_id)

    def decay(self, now: float | None = None, ttl_seconds: int | None = None) -> list[Lesson]:
        ttl = self._ttl_seconds if ttl_seconds is None else ttl_seconds
        return self._store.decay(now=now, ttl_seconds=ttl)
