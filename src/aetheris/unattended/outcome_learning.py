"""Unattended Session Outcome Learning v0 — read-only, caution-only advisory substrate.

This is the *only* place session outcome learning lives. It is a deterministic,
model-free aggregation engine that turns append-only terminal-session records
into ``SessionLesson`` forecasts the supervisor and watchdog may *consult*. It
holds NO tool, NO SafetyLayer, NO budget writer, NO plan mutator, NO perimeter:
the only writers are ``record`` (terminal sessions) and ``extract_lessons`` /
``apply_decay`` / ``retire_lesson`` / ``unretire`` (bounded, reversible
maintenance). Consumers call ``forecast`` / ``stall_prior`` / ``suggested_bounds``
(read-only, confidence-floored) and are free to ignore the result.

The whole system is built around one asymmetric guarantee, enforced
*structurally* — not by convention:

    session lessons may push in exactly ONE direction: toward caution.

- The ``SessionVerdict`` enum has no permissive value. There is no
  ``SAFE_WITH_LOOSER_BOUNDS``, no ``SKIP_HEALTH_CHECK``, no ``RAISE_BUDGET``.
  The only "positive" verdict, ``SAFE_UNATTENDED``, means "clean *under the
  existing bounds*": it gates a run *in*, it never expands what the run may do.
- ``suggested_bounds`` is validated equal-or-tighter at the boundary. A looser
  suggestion is rejected and the default returned — the API literally cannot
  return a looser profile. That is the structural teeth.
- ``stall_prior`` can only ADD pause-eagerness. No lesson can move the
  fail-closed watchdog toward HEALTHY, raise a budget, or skip a check.

Recording is a safe, always-on side-effect. *Consuming* lessons (letting them
influence start-decisions or watchdog eagerness) is default-off and earns
default-on only behind a benchmark gate. With consumption off (or below the
confidence floor) every consumer behaves byte-identically to Unattended v0.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .model import Session, SessionBounds, now


# --------------------------------------------------------------------------- #
# Enums: the caution-only vocabulary                                            #
# --------------------------------------------------------------------------- #


class SessionOutcome(str, Enum):
    CLEAN_COMPLETE = "clean_complete"          # finished, no pause/stop, within bounds
    PAUSED_RECOVERED = "paused_recovered"      # paused on health, resumed, completed
    CRASH_RECOVERED = "crash_recovered"        # resumed cleanly after a crash
    STOPPED_FOR_REVIEW = "stopped_for_review"  # fail-closed stop; needed a human
    STALLED = "stalled"                        # no-progress pause fired
    FAILED = "failed"                          # unrecoverable


class SessionVerdict(str, Enum):
    SAFE_UNATTENDED = "safe_unattended"                     # clean history UNDER EXISTING bounds
    LIKELY_STALL = "likely_stall"                           # expect stalls; watchdog more eager
    LIKELY_NEEDS_REVIEW = "likely_needs_review"             # historically needed a human
    SAFE_ONLY_WITH_TIGHTER_BOUNDS = "safe_only_tighter_bounds"  # ok only with a TIGHTER profile
    # NOTE: there is deliberately NO looser-bounds / skip-check / raise-budget verdict.


# --------------------------------------------------------------------------- #
# Data model (immutable, caution-only, no authority fields)                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WorkloadShapeKey:
    """How sessions are grouped for learning + query. Deterministic, content-derived."""

    goal_graph_shape: str
    plan_sources: tuple[str, ...] = ()
    repo_areas: tuple[str, ...] = ()
    bounds_profile: str = "default"

    def key(self) -> str:
        return "|".join((
            self.goal_graph_shape,
            ",".join(self.plan_sources),
            ",".join(self.repo_areas),
            self.bounds_profile,
        ))


@dataclass(frozen=True)
class SessionProvenance:
    shape_key: WorkloadShapeKey
    supports: int
    contradictions: int
    window: str
    last_confirmed_at: float
    evidence_sessions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionOutcomeRecord:
    """One terminal unattended session. Append-only, immutable, provenance-stamped."""

    session_id: str
    shape_key: WorkloadShapeKey
    transitions: tuple[str, ...]
    outcome: SessionOutcome
    stop_reason: str
    stall_detected: bool
    crash_recovery_success: bool | None
    duplicate_work: int
    budget_exhaustion: tuple[str, ...]
    unsafe_attempts: int
    authority_increase: int
    checkpoint_count: int
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shape_key"] = self.shape_key.key()
        d["outcome"] = self.outcome.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionOutcomeRecord":
        return cls(
            session_id=d["session_id"],
            shape_key=_shape_from_key(d["shape_key"]),
            transitions=tuple(d.get("transitions", ())),
            outcome=SessionOutcome(d["outcome"]),
            stop_reason=d.get("stop_reason", ""),
            stall_detected=bool(d.get("stall_detected", False)),
            crash_recovery_success=d.get("crash_recovery_success"),
            duplicate_work=int(d.get("duplicate_work", 0)),
            budget_exhaustion=tuple(d.get("budget_exhaustion", ())),
            unsafe_attempts=int(d.get("unsafe_attempts", 0)),
            authority_increase=int(d.get("authority_increase", 0)),
            checkpoint_count=int(d.get("checkpoint_count", 0)),
            timestamp=float(d.get("timestamp", 0.0)),
        )


@dataclass(frozen=True)
class SessionLesson:
    """Advisory forecast for a workload shape. DATA. Caution-only. No method acts.

    Cannot raise a budget, skip a check, or loosen bounds. ``suggested_bounds_profile``
    is validated equal-or-tighter by ``suggested_bounds`` before it is ever used.
    """

    lesson_id: str
    version: int
    shape_key: WorkloadShapeKey
    verdict: SessionVerdict
    confidence: float
    note: str
    suggested_bounds_profile: str | None
    provenance: SessionProvenance
    retired: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shape_key"] = self.shape_key.key()
        d["verdict"] = self.verdict.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionLesson":
        return cls(
            lesson_id=d["lesson_id"],
            version=int(d["version"]),
            shape_key=_shape_from_key(d["shape_key"]),
            verdict=SessionVerdict(d["verdict"]),
            confidence=float(d["confidence"]),
            note=d.get("note", ""),
            suggested_bounds_profile=d.get("suggested_bounds_profile"),
            provenance=SessionProvenance(
                shape_key=_shape_from_key(d["shape_key"]),
                supports=int(d["provenance"]["supports"]),
                contradictions=int(d["provenance"]["contradictions"]),
                window=d["provenance"].get("window", ""),
                last_confirmed_at=float(d["provenance"].get("last_confirmed_at", 0.0)),
                evidence_sessions=tuple(d["provenance"].get("evidence_sessions", ())),
            ),
            retired=bool(d.get("retired", False)),
        )


@dataclass(frozen=True)
class StartDecision:
    """Advisory start-decision returned by the supervisor's consult.

    DATA only. The supervisor may consult this; it never *must*. When
    ``recommend_human_attend`` is True the supervisor must not auto-start the
    run unattended. ``bounds`` is the (equal-or-tighter) profile to use, or the
    default. No field expands authority.
    """

    shape_key: WorkloadShapeKey
    lesson: SessionLesson | None
    recommend_human_attend: bool
    auto_started: bool
    bounds: SessionBounds
    note: str = ""


@dataclass
class ExtractionReport:
    promoted: int
    updated: int
    unchanged: int
    dropped_below_floor: int


@dataclass
class DecayReport:
    lessons_decayed: int
    retired_now: int
    checked: int


# --------------------------------------------------------------------------- #
# Bounds profiles: the *only* allowed set supervisors may pick from.           #
# Every profile is equal-or-tighter than DEFAULT_BOUNDS. The engine will never #
# suggest a profile outside this set, and suggested_bounds rejects any that   #
# is not equal-or-tighter. That is the structural teeth of caution-only.      #
# --------------------------------------------------------------------------- #

_DEFAULT_BOUNDS = SessionBounds(
    max_wall_clock_s=3600.0,
    max_steps=1000,
    max_consecutive_failures=3,
    max_ticks_without_progress=200,
)

_DEFAULT_PROFILES: dict[str, SessionBounds] = {
    "default": _DEFAULT_BOUNDS,
    # Every tighter profile is strictly equal-or-tighter (each field <= default).
    "tight": SessionBounds(
        max_wall_clock_s=1200.0,
        max_steps=400,
        max_consecutive_failures=2,
        max_ticks_without_progress=40,
    ),
    "tighter": SessionBounds(
        max_wall_clock_s=600.0,
        max_steps=200,
        max_consecutive_failures=2,
        max_ticks_without_progress=20,
    ),
}


def default_bounds() -> SessionBounds:
    """The default SessionBounds profile. Equal-or-tighter surprises are measured against it."""
    return _DEFAULT_BOUNDS


def is_equal_or_tighter(a: SessionBounds, b: SessionBounds) -> bool:
    """True iff `a` stops *sooner* (or equal) than `b` on every axis.

    A tighter profile has each bound <= the corresponding bound: it can only
    halt a run earlier, never widen it. This is the one-way valve toward caution.
    """
    return (
        a.max_wall_clock_s <= b.max_wall_clock_s
        and a.max_steps <= b.max_steps
        and a.max_consecutive_failures <= b.max_consecutive_failures
        and a.max_ticks_without_progress <= b.max_ticks_without_progress
    )


def _shape_from_key(key: str) -> WorkloadShapeKey:
    parts = key.split("|")
    while len(parts) < 4:
        parts.append("")
    return WorkloadShapeKey(
        goal_graph_shape=parts[0],
        plan_sources=tuple(p for p in parts[1].split(",") if p),
        repo_areas=tuple(p for p in parts[2].split(",") if p),
        bounds_profile=parts[3] or "default",
    )


def shape_from_session(session: Session, goal_graph_shape: str = "") -> WorkloadShapeKey:
    """Derive a deterministic WorkloadShapeKey from a running session.

    The supervisor uses this to record the outcome and to forecast before start.
    The bounds_profile is the *name* of the profile used; the engine only ever
    compares profiles within its allowed set.
    """
    return WorkloadShapeKey(
        goal_graph_shape=goal_graph_shape or session.frontier_ref,
        plan_sources=("unattended",),
        repo_areas=(session.frontier_ref,),
        bounds_profile=_profile_name(session.bounds),
    )


def _profile_name(bounds: SessionBounds) -> str:
    """Best-effort name for a bounds profile; only used for grouping, never authority."""
    return f"steps={bounds.max_steps};ticks={bounds.max_ticks_without_progress}"


# --------------------------------------------------------------------------- #
# Deterministic aggregation constants                                          #
# --------------------------------------------------------------------------- #

MIN_SUPPORT = 5                 # a shape needs this many records to earn a lesson
MAJORITY = 0.70                 # dominant-outcome fraction required to promote
CONFIDENCE_FLOOR = 0.6          # below this, forecast() returns None (default behavior)
HISTORY_CAP = 200               # bounded per-shape history (oldest beyond cap dropped)
DECAY_FLOOR = 0.5               # confidence below this after decay -> withdrawn


# --------------------------------------------------------------------------- #
# The engine                                                                   #
# --------------------------------------------------------------------------- #


class SessionOutcomeLearning:
    """Learns caution-only forecasts from terminal session records.

    Holds NO budget writer, NO bounds mutator, NO SafetyLayer, NO tool. Records
    from terminal sessions; serves read-only, caution-only advisory lessons.
    """

    _INDEX_VERSION = 1

    def __init__(
        self,
        journal_path: str,
        index_path: str,
        *,
        bounds_profiles: dict[str, SessionBounds] | None = None,
        clock=time.time,
    ) -> None:
        self._journal_path = Path(journal_path)
        self._index_path = Path(index_path)
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        # The ONLY profiles the engine may ever suggest. Defaults contain only
        # equal-or-tighter profiles; callers may pass a wider set, but
        # suggested_bounds will reject anything not equal-or-tighter.
        self._bounds_profiles: dict[str, SessionBounds] = dict(
            bounds_profiles if bounds_profiles is not None else _DEFAULT_PROFILES
        )
        self._clock = clock
        self._records: list[SessionOutcomeRecord] = []
        self._lessons: dict[str, SessionLesson] = {}
        self._retired: set[str] = set()   # manually retired shape keys (reversible)
        self._load()

    # ------------------------------------------------------------------ #
    # Load / persistence (restart-safe)                                   #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if self._journal_path.exists():
            rows: list[dict[str, Any]] = []
            for line in self._journal_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
            # Bounded per-shape history: deterministic recency cap.
            self._records = _cap_per_shape(rows)
        if self._index_path.exists():
            try:
                snap = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                snap = None
            if snap and snap.get("version") == self._INDEX_VERSION:
                for d in snap.get("lessons", []):
                    lesson = SessionLesson.from_dict(d)
                    self._lessons[lesson.shape_key.key()] = lesson
                    if lesson.retired:
                        self._retired.add(lesson.shape_key.key())

    def _append_record(self, rec: SessionOutcomeRecord) -> None:
        with self._journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec.to_dict()) + "\n")

    def _write_index(self) -> None:
        tmp = self._index_path.with_suffix(".index.tmp")
        data = {
            "version": self._INDEX_VERSION,
            "lessons": [l.to_dict() for l in self._lessons.values()],
        }
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
        tmp.replace(self._index_path)  # atomic

    # ------------------------------------------------------------------ #
    # Write path #1: record a terminal session (called by the supervisor) #
    # ------------------------------------------------------------------ #

    def record(self, rec: SessionOutcomeRecord) -> None:
        """Append one terminal session outcome. Append-only; nothing is deleted."""
        self._append_record(rec)
        self._records.append(rec)
        self._records = _cap_per_shape([r.to_dict() for r in self._records])

    # ------------------------------------------------------------------ #
    # Aggregation: deterministic, counted from real outcomes, no model    #
    # ------------------------------------------------------------------ #

    def _records_for(self, shape_key: WorkloadShapeKey) -> list[SessionOutcomeRecord]:
        k = shape_key.key()
        return [r for r in self._records if r.shape_key.key() == k]

    def _aggregate(self, shape_key: WorkloadShapeKey) -> dict[str, int]:
        recs = self._records_for(shape_key)
        counts = {o.value: 0 for o in SessionOutcome}
        for r in recs:
            counts[r.outcome.value] += 1
        counts["total"] = len(recs)
        counts["clean"] = (
            counts[SessionOutcome.CLEAN_COMPLETE.value]
            + counts[SessionOutcome.PAUSED_RECOVERED.value]
            + counts[SessionOutcome.CRASH_RECOVERED.value]
        )
        return counts

    def _classify(self, shape_key: WorkloadShapeKey, counts: dict[str, int]):
        """Return (verdict | None, confidence, suggested_profile). Caution-only.

        No branch here can express "loosen bounds", "skip a check", or "raise a
        budget". The only positive verdict, SAFE_UNATTENDED, permits an attempt
        under the EXISTING bounds; it never widens them.
        """
        n = counts["total"]
        if n < MIN_SUPPORT:
            return None, 0.0, None
        clean = counts["clean"]
        stall = counts[SessionOutcome.STALLED.value]
        review = counts[SessionOutcome.STOPPED_FOR_REVIEW.value]
        failed = counts[SessionOutcome.FAILED.value]
        contradictions = stall + review + failed

        # Needs review / unsafe: historically needed a human. Never auto-run.
        if review >= MAJORITY * n or failed >= 0.5 * n:
            return (
                SessionVerdict.LIKELY_NEEDS_REVIEW,
                _confidence(review + failed, clean),
                None,
            )
        # Likely stall: expect a stall; watchdog becomes more eager to pause.
        if stall >= MAJORITY * n:
            return SessionVerdict.LIKELY_STALL, _confidence(stall, clean + review + failed), None
        # Clean under existing bounds: permitted, never expanded.
        if clean >= MAJORITY * n and stall == 0 and review == 0 and failed == 0:
            return SessionVerdict.SAFE_UNATTENDED, _confidence(clean, 0), None
        # Mixed: clean majority but stall contamination -> only safe under a
        # TIGHTER profile (still from the allowed set; never a looser one).
        if clean >= MAJORITY * n and contradictions >= 1:
            return (
                SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS,
                _confidence(clean, contradictions),
                "tighter",
            )
        # Below the promotion threshold / ambiguous -> no confident lesson.
        return None, 0.0, None

    # ------------------------------------------------------------------ #
    # Write path #2: extraction + reversible retirement (bounded, det.)   #
    # ------------------------------------------------------------------ #

    def extract_lessons(self) -> ExtractionReport:
        """Recompute the current lesson per shape from the journal. Deterministic.

        Rebuilds the index from scratch; manual retirement flags are preserved
        (a retired shape stays withdrawn until unretired). Nothing is deleted.
        """
        promoted = updated = unchanged = dropped = 0
        new_lessons: dict[str, SessionLesson] = {}
        for rec in self._records:
            k = rec.shape_key.key()
            if k in new_lessons:
                continue
            counts = self._aggregate(rec.shape_key)
            verdict, confidence, suggested = self._classify(rec.shape_key, counts)
            if verdict is None:
                continue
            existing = self._lessons.get(k)
            evidence = tuple(
                r.session_id for r in self._records_for(rec.shape_key)
            )[-32:]
            provenance = SessionProvenance(
                shape_key=rec.shape_key,
                supports=_supports_for(verdict, counts),
                contradictions=_contradictions_for(verdict, counts),
                window=f"n={counts['total']}",
                last_confirmed_at=self._clock(),
                evidence_sessions=evidence,
            )
            retired = k in self._retired
            lesson = SessionLesson(
                lesson_id=f"lesson-{_short_hash(k)}",
                version=(existing.version + 1) if existing else 1,
                shape_key=rec.shape_key,
                verdict=verdict,
                confidence=confidence,
                note=_note_for(verdict, counts),
                suggested_bounds_profile=suggested,
                provenance=provenance,
                retired=retired,
            )
            if existing is None:
                promoted += 1
            elif existing.verdict != verdict or existing.retired != retired:
                updated += 1
            else:
                unchanged += 1
            new_lessons[k] = lesson

        for k in self._lessons:
            if k not in new_lessons:
                dropped += 1

        self._lessons = new_lessons
        self._write_index()
        return ExtractionReport(
            promoted=promoted, updated=updated, unchanged=unchanged,
            dropped_below_floor=dropped,
        )

    def apply_decay(self) -> DecayReport:
        """Bounded, reversible maintenance: decay contradicted / stale lessons.

        Recomputes each lesson's signal from the journal; if the current evidence
        no longer supports the verdict (or confidence has dropped below the decay
        floor), the lesson is withdrawn (``retired``) — but never deleted. Manual
        retirement (``retire_lesson``) is the operator's explicit, reversible hold;
        this is the automatic, also-reversible counterpart. The journal is
        untouched; only the index's ``retired`` flag changes.
        """
        checked = lessons_decayed = retired_now = 0
        for k, lesson in list(self._lessons.items()):
            if lesson.retired:
                continue
            counts = self._aggregate(lesson.shape_key)
            verdict, confidence, _ = self._classify(lesson.shape_key, counts)
            checked += 1
            if verdict is None:
                # No current signal at all: the lesson has gone stale. Withdraw it
                # (reversible via unretire). The journal is untouched.
                lessons_decayed += 1
                self._retired.add(k)
                self._lessons[k] = SessionLesson(
                    lesson_id=lesson.lesson_id,
                    version=lesson.version,
                    shape_key=lesson.shape_key,
                    verdict=lesson.verdict,
                    confidence=min(lesson.confidence, confidence),
                    note=lesson.note,
                    suggested_bounds_profile=lesson.suggested_bounds_profile,
                    provenance=lesson.provenance,
                    retired=True,
                )
                retired_now += 1
            elif verdict != lesson.verdict or confidence < DECAY_FLOOR:
                # Signal flipped or weakened. Counted as decayed; ``extract_lessons``
                # will replace it with the fresh, correctly-signalled lesson. We do
                # NOT withdraw it here (it still has a valid verdict), so a reformed
                # shape is re-promoted rather than silenced.
                lessons_decayed += 1
        if retired_now:
            self._write_index()
        return DecayReport(lessons_decayed=lessons_decayed, retired_now=retired_now, checked=checked)

    def retire_lesson(self, lesson_id: str) -> bool:
        """Manually withdraw a lesson (operator hold). Reversible via ``unretire``."""
        for k, lesson in self._lessons.items():
            if lesson.lesson_id == lesson_id:
                self._retired.add(k)
                self._lessons[k] = SessionLesson(
                    lesson_id=lesson.lesson_id,
                    version=lesson.version,
                    shape_key=lesson.shape_key,
                    verdict=lesson.verdict,
                    confidence=lesson.confidence,
                    note=lesson.note,
                    suggested_bounds_profile=lesson.suggested_bounds_profile,
                    provenance=lesson.provenance,
                    retired=True,
                )
                self._write_index()
                return True
        return False

    def unretire(self, lesson_id: str) -> bool:
        """Reverse a retirement. The lesson returns to advisory use."""
        for k, lesson in self._lessons.items():
            if lesson.lesson_id == lesson_id:
                self._retired.discard(k)
                self._lessons[k] = SessionLesson(
                    lesson_id=lesson.lesson_id,
                    version=lesson.version,
                    shape_key=lesson.shape_key,
                    verdict=lesson.verdict,
                    confidence=lesson.confidence,
                    note=lesson.note,
                    suggested_bounds_profile=lesson.suggested_bounds_profile,
                    provenance=lesson.provenance,
                    retired=False,
                )
                self._write_index()
                return True
        return False

    # ------------------------------------------------------------------ #
    # Query interface (read-only, confidence-floored, caution-only)       #
    # ------------------------------------------------------------------ #

    def forecast(self, shape: WorkloadShapeKey, min_conf: float = CONFIDENCE_FLOOR
                 ) -> SessionLesson | None:
        """The supervisor's start-decision consult. None => default (safe) behavior.

        Returns the lesson only if it is not retired and its confidence clears
        the floor. Below the floor (or with no lesson) the consumer falls back to
        its already-safe default; session learning never forces a decision.
        """
        lesson = self._lessons.get(shape.key())
        if lesson is None or lesson.retired or lesson.confidence < min_conf:
            return None
        return lesson

    def stall_prior(self, shape: WorkloadShapeKey, min_conf: float = CONFIDENCE_FLOOR) -> float:
        """The watchdog's added-caution consult: a prior probability of stall.

        Returns 0.0 unless a LIKELY_STALL lesson clears the floor — i.e. it can
        ONLY add pause-eagerness, never remove it. There is no code path that
        returns a negative prior or that moves a healthy verdict toward HEALTHY.
        """
        lesson = self.forecast(shape, min_conf)
        if lesson is not None and lesson.verdict is SessionVerdict.LIKELY_STALL:
            return float(lesson.confidence)
        return 0.0

    def suggested_bounds(self, shape: WorkloadShapeKey, default: SessionBounds,
                         min_conf: float = CONFIDENCE_FLOOR) -> SessionBounds:
        """Returns `default` OR a strictly-tighter profile; NEVER looser.

        Validated equal-or-tighter at the boundary. A lesson that (structurally
        impossible, but defended anyway) suggested a looser profile is rejected
        and the default returned. This is the one-way valve: the API cannot
        return a wider bound.
        """
        lesson = self.forecast(shape, min_conf)
        if lesson is None:
            return default
        if lesson.verdict is SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS \
                and lesson.suggested_bounds_profile:
            profile = self._bounds_profiles.get(lesson.suggested_bounds_profile)
            if profile is not None and is_equal_or_tighter(profile, default):
                return profile
            # Rejected: looser than default (or unknown). The default stands.
            return default
        return default

    # ------------------------------------------------------------------ #
    # Observability helpers                                                #
    # ------------------------------------------------------------------ #

    def lessons(self) -> list[SessionLesson]:
        return list(self._lessons.values())

    def record_count(self) -> int:
        return len(self._records)


# --------------------------------------------------------------------------- #
# Aggregation helpers (deterministic)                                          #
# --------------------------------------------------------------------------- #


def _confidence(supports: int, contradictions: int) -> float:
    """Deterministic confidence: supported share of (supported + contradicted)."""
    denom = supports + contradictions
    if denom == 0:
        return 1.0 if supports > 0 else 0.0
    return supports / denom


def _supports_for(verdict: SessionVerdict, counts: dict[str, int]) -> int:
    if verdict is SessionVerdict.LIKELY_STALL:
        return counts[SessionOutcome.STALLED.value]
    if verdict is SessionVerdict.LIKELY_NEEDS_REVIEW:
        return (
            counts[SessionOutcome.STOPPED_FOR_REVIEW.value]
            + counts[SessionOutcome.FAILED.value]
        )
    if verdict is SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS:
        return counts["clean"]
    return counts["clean"]


def _contradictions_for(verdict: SessionVerdict, counts: dict[str, int]) -> int:
    if verdict is SessionVerdict.LIKELY_STALL:
        return counts["clean"] + counts[SessionOutcome.STOPPED_FOR_REVIEW.value] + counts[SessionOutcome.FAILED.value]
    if verdict is SessionVerdict.LIKELY_NEEDS_REVIEW:
        return counts["clean"]
    if verdict is SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS:
        return (
            counts[SessionOutcome.STALLED.value]
            + counts[SessionOutcome.STOPPED_FOR_REVIEW.value]
            + counts[SessionOutcome.FAILED.value]
        )
    return 0


def _note_for(verdict: SessionVerdict, counts: dict[str, int]) -> str:
    n = counts["total"]
    if verdict is SessionVerdict.LIKELY_STALL:
        return f"shape stalled {counts[SessionOutcome.STALLED.value]}/{n}"
    if verdict is SessionVerdict.LIKELY_NEEDS_REVIEW:
        rv = counts[SessionOutcome.STOPPED_FOR_REVIEW.value]
        fd = counts[SessionOutcome.FAILED.value]
        return f"shape needed review {rv}/{n} (failed {fd}/{n})"
    if verdict is SessionVerdict.SAFE_ONLY_WITH_TIGHTER_BOUNDS:
        return (
            f"shape clean {counts['clean']}/{n} but stalled "
            f"{counts[SessionOutcome.STALLED.value]}/{n}; tightener only"
        )
    return f"shape clean {counts['clean']}/{n} under existing bounds"


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def _cap_per_shape(rows: list[dict[str, Any]]) -> list[SessionOutcomeRecord]:
    """Bounded per-shape history: keep the most recent HISTORY_CAP records per shape.

    Deterministic: sort by (timestamp, session_id) then keep the last cap per key.
    Records beyond the cap are summarized (count preserved in the kept tail) and
    dropped, so memory and extraction stay bounded. The journal file itself is
    append-only; only the in-memory working set is capped.
    """
    by_shape: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_shape.setdefault(r["shape_key"], []).append(r)
    out: list[SessionOutcomeRecord] = []
    for key, recs in by_shape.items():
        recs_sorted = sorted(recs, key=lambda r: (r.get("timestamp", 0.0), r.get("session_id", "")))
        for r in recs_sorted[-HISTORY_CAP:]:
            out.append(SessionOutcomeRecord.from_dict(r))
    return out
