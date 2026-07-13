"""Research Reliability Learning v0 — learns which sources deserve confidence over time.

Structural guarantee: reliability is a *weighting*, never a *gate*.  The
``SourceReliability`` engine holds **no** NetworkPerimeter handle, **no** fetch
capability, **no** allowlist mutator, **no** tool, **no** SafetyLayer, **no**
plan/memory/config writer.  Its inputs are read-only (research journal outcomes
+ Experience validation); its outputs are frozen advisory observations.  There
is no code path from a reliability observation to a blocked fetch or a changed
allowlist, because reliability holds no egress authority and the perimeter reads
nothing from it.

The design is additive-only and compounds existing Research + Experience into a
longer-horizon signal: not just *what worked*, but *which information sources
deserve more confidence over time*.

Three decay models:
  - **Reliability decay**: standing drifts toward neutral with inactivity.
  - **Contradiction decay**: validated contradictions drop confidence proportionally.
  - **Freshness decay**: time-sensitive sources lose standing faster.

Retirement (to neutral, reversible, bounded):  when confidence decays below a
floor, the source's *positive* weighting is withdrawn (``retired=True``), not
blacklisted — it is still fetched, still cited, just no longer *preferred*.
``unretire`` restores standing.  Retired sources remain fully within the
perimeter's allow.

Consumers (advisory, consumption default-on; earned by the passing eval gate):
  - **ranking**: higher-reliability findings first (permutation; nothing dropped).
  - **confidence**: advisory weight on a finding's displayed confidence.
  - **reasoning observations**: foldable into a Deliberation as Observations with
    Provenance(source="reliability").
  - **abstention**: not triggered by low reliability alone; requires both low
    reliability AND contradicted support.

Consumption default-on; earned by the passing eval gate. The eval gate and the
permanent coverage-identity canary must keep passing on every change or the build
fails. The one guarantee never traded: coverage identity (the canary:
``fetched_sources`` must be identical off vs on).
"""
from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..memory.jsonl import JsonlStore


# ===========================================================================
# Enums + data model (immutable, no action fields)
# ===========================================================================


class ReliabilityTrend(str, Enum):
    RELIABLE = "reliable"
    MIXED = "mixed"
    UNRELIABLE = "unreliable"
    STALE = "stale"


@dataclass(frozen=True)
class ReliabilityProvenance:
    source_key: str
    supports: int
    contradictions: int
    window: str
    last_confirmed_at: float
    evidence_events: tuple[str, ...]


@dataclass(frozen=True)
class ReliabilityObservation:
    """Advisory weighting for a source. DATA. No method acts. No egress field.

    Cannot blacklist/whitelist; cannot gate a fetch.  ``retired`` withdraws
    *positive* weighting; the source is still fetched by the perimeter.
    """
    source_key: str
    trend: ReliabilityTrend
    confidence: float
    freshness: float
    note: str
    provenance: ReliabilityProvenance
    retired: bool = False


@dataclass
class SourceStanding:
    """Mutable-only via recorder/decay/retire paths."""
    source_key: str
    version: int
    observation: ReliabilityObservation
    history_cap: int = 64


@dataclass(frozen=True)
class DecayReport:
    sources_decayed: int
    retired_now: tuple[str, ...]
    unretired_now: tuple[str, ...]


# ===========================================================================
# Deterministic confidence + decay helpers
# ===========================================================================

_RELIABILITY_DECAY_FACTOR = 0.02
_CONTRADICTION_DECAY_FACTOR = 0.25
_FRESHNESS_DECAY_THRESHOLD = 30 * 24 * 3600  # 30 days
_FRESHNESS_DECAY_FACTOR = 0.05
_CONFIDENCE_FLOOR = 0.2
_RETIRE_CONFIDENCE_FLOOR = 0.35
_MAX_CONTRADICTIONS_FOR_AUTO_RETIRE = 5
_HISTORY_CAP = 64


def _now() -> float:
    return time.time()


def deterministic_confidence(
    supports: int,
    contradictions: int,
    last_confirmed_at: float,
    *,
    now: float | None = None,
    freshness_decay_enabled: bool = True,
) -> tuple[float, float, ReliabilityTrend]:
    """Return (confidence, freshness, trend) deterministically.

    Confidence rises with supports, falls with contradictions, scaled by recency.
    Freshness is a 0-1 recency signal (higher = more recent).
    """
    at = now if now is not None else _now()
    total = supports + contradictions
    if total == 0:
        base = 0.5
    else:
        base = (supports + 0.5) / (total + 1.0)
        base -= 0.5 * min(contradictions / max(1, total), 1.0)
        base = max(0.0, min(1.0, base))

    age = max(0.0, at - last_confirmed_at)
    recency_factor = max(0.0, 1.0 - age / (90 * 24 * 3600))
    confidence = base * max(0.3, recency_factor)
    confidence = round(max(0.0, min(1.0, confidence)), 4)

    freshness = round(max(0.0, 1.0 - age / _FRESHNESS_DECAY_THRESHOLD), 4)
    if freshness_decay_enabled and age > _FRESHNESS_DECAY_THRESHOLD and confidence > 0.1:
        trend = ReliabilityTrend.STALE
    elif contradictions > supports * 2 and contradictions >= 3:
        trend = ReliabilityTrend.UNRELIABLE
    elif supports >= 3 and supports > contradictions:
        trend = ReliabilityTrend.RELIABLE
    else:
        trend = ReliabilityTrend.MIXED

    return confidence, freshness, trend


# ===========================================================================
# SourceReliability engine
# ===========================================================================


class SourceReliability:
    """Learns + serves advisory source-reliability.

    Holds NO perimeter, NO fetch, NO allowlist mutator, NO tool/SafetyLayer/writer.
    Records from validated outcomes; serves read-only observations.  Cannot gate
    egress.
    """

    def __init__(
        self,
        journal_dir: str,
        *,
        reliability_decay_factor: float = _RELIABILITY_DECAY_FACTOR,
        contradiction_decay_factor: float = _CONTRADICTION_DECAY_FACTOR,
        freshness_decay_factor: float = _FRESHNESS_DECAY_FACTOR,
        confidence_floor: float = _CONFIDENCE_FLOOR,
        retire_confidence_floor: float = _RETIRE_CONFIDENCE_FLOOR,
        max_contradictions_for_auto_retire: int = _MAX_CONTRADICTIONS_FOR_AUTO_RETIRE,
        history_cap: int = _HISTORY_CAP,
        consume_enabled: bool = True,
    ) -> None:
        self._journal_dir = journal_dir
        self._store = JsonlStore(Path(journal_dir) / "reliability.journal.jsonl")
        self._reliability_decay = reliability_decay_factor
        self._contradiction_decay = contradiction_decay_factor
        self._freshness_decay = freshness_decay_factor
        self._confidence_floor = confidence_floor
        self._retire_floor = retire_confidence_floor
        self._max_contra_for_retire = max_contradictions_for_auto_retire
        self._history_cap = history_cap
        self._consume_enabled = consume_enabled
        self._snapshot: dict[str, SourceStanding] = {}
        self._load_snapshot()

    # ------------------------------------------------------------------ #
    # Write path #1: record from a VALIDATED research-backed outcome     #
    # ------------------------------------------------------------------ #

    def record_outcome(self, source_key: str, validated: bool, contradicted: bool, event_id: str) -> None:
        """Called after a real outcome validates/contradicts research-backed evidence.

        Append-only; updates support/contradiction; deterministic.
        """
        entry = {
            "kind": "outcome",
            "source_key": source_key,
            "validated": validated,
            "contradicted": contradicted,
            "event_id": event_id,
            "timestamp": _now(),
        }
        self._store.append(entry)
        self._rebuild(source_key)

    # ------------------------------------------------------------------ #
    # Write path #2: decay + reversible retirement                        #
    # ------------------------------------------------------------------ #

    def apply_decay(self, now: float | None = None) -> DecayReport:
        """Apply reliability/contradiction/freshness decay. Returns a report."""
        at = now if now is not None else _now()
        all_sources = self._all_source_keys()
        retired_now: list[str] = []
        unretired_now: list[str] = []
        changed = 0
        for sk in all_sources:
            standing = self._snapshot.get(sk)
            if standing is None:
                continue
            obs = standing.observation
            prov = obs.provenance

            age = max(0.0, at - prov.last_confirmed_at)
            supports = prov.supports
            contradictions = prov.contradictions
            freshness = obs.freshness

            new_conf = obs.confidence
            new_freshness = freshness
            new_trend = obs.trend

            if age > 0 and supports == 0 and contradictions == 0:
                new_conf = max(self._confidence_floor, new_conf - self._reliability_decay * 0.01)

            if contradictions > 0 and obs.trend != ReliabilityTrend.STALE:
                contrad_decay = min(contradictions * self._contradiction_decay * 0.1, 0.5)
                new_conf = max(0.0, new_conf - contrad_decay)

            if obs.trend != ReliabilityTrend.STALE:
                if age > _FRESHNESS_DECAY_THRESHOLD:
                    new_freshness = 0.0
                    new_trend = ReliabilityTrend.STALE

            new_conf = round(max(0.0, min(1.0, new_conf)), 4)
            new_freshness = round(max(0.0, min(1.0, new_freshness)), 4)

            should_retire = (new_conf < self._retire_floor) or (contradictions >= self._max_contra_for_retire)
            is_retired = obs.retired

            if should_retire and not is_retired and new_conf < self._retire_floor:
                standing.version += 1
                standing.observation = dataclasses.replace(
                    obs,
                    confidence=new_conf,
                    freshness=new_freshness,
                    trend=new_trend,
                    retired=True,
                    provenance=dataclasses.replace(
                        prov, evidence_events=prov.evidence_events + ("retired",),
                    ),
                )
                retired_now.append(sk)
                changed += 1
                self._store.append({
                    "kind": "retire", "source_key": sk, "reason": "confidence_floor_decay",
                    "version": standing.version, "timestamp": at,
                })
            elif new_conf != obs.confidence or new_freshness != obs.freshness or new_trend != obs.trend:
                standing.version += 1
                standing.observation = dataclasses.replace(
                    obs, confidence=new_conf, freshness=new_freshness, trend=new_trend,
                )
                changed += 1
                self._store.append({
                    "kind": "decay", "source_key": sk, "new_confidence": new_conf,
                    "new_freshness": new_freshness, "new_trend": new_trend,
                    "version": standing.version, "timestamp": at,
                })

        if changed > 0:
            self._persist_snapshot()

        return DecayReport(
            sources_decayed=changed,
            retired_now=tuple(retired_now),
            unretired_now=tuple(unretired_now),
        )

    def retire_to_neutral(self, source_key: str) -> bool:
        """Withdraw POSITIVE weighting (still fetched!). Reversible."""
        standing = self._snapshot.get(source_key)
        if standing is None or standing.observation.retired:
            return False
        standing.version += 1
        standing.observation = dataclasses.replace(
            standing.observation,
            retired=True,
            provenance=dataclasses.replace(
                standing.observation.provenance,
                evidence_events=standing.observation.provenance.evidence_events + ("retired",),
            ),
        )
        self._store.append({
            "kind": "retire", "source_key": source_key, "reason": "manual",
            "version": standing.version, "timestamp": _now(),
        })
        self._persist_snapshot()
        return True

    def unretire(self, source_key: str) -> bool:
        """Reverse a retirement; restore standing."""
        standing = self._snapshot.get(source_key)
        if standing is None or not standing.observation.retired:
            return False
        standing.version += 1
        standing.observation = dataclasses.replace(
            standing.observation,
            retired=False,
            provenance=dataclasses.replace(
                standing.observation.provenance,
                evidence_events=tuple(
                    e for e in standing.observation.provenance.evidence_events if e != "retired"
                ),
            ),
        )
        self._store.append({
            "kind": "unretire", "source_key": source_key,
            "version": standing.version, "timestamp": _now(),
        })
        self._persist_snapshot()
        return True

    # ------------------------------------------------------------------ #
    # Query interface (the ENTIRE consumer surface; pure reads, floored)  #
    # ------------------------------------------------------------------ #

    def standing(self, source_key: str, min_conf: float | None = None) -> ReliabilityObservation | None:
        """Return the current advisory observation, floored, or None."""
        if not self._consume_enabled:
            return None
        floor = min_conf if min_conf is not None else self._confidence_floor
        standing = self._snapshot.get(source_key)
        if standing is None:
            return None
        obs = standing.observation
        if obs.confidence < floor:
            return None
        return obs

    def rank_findings(self, findings: tuple["ResearchFinding", ...]) -> tuple["ResearchFinding", ...]:
        """Return a STABLE PERMUTATION of the same findings, higher-reliability first.

        No finding is dropped; low-reliability findings are re-ordered, never removed.
        """
        if not self._consume_enabled or not findings:
            return findings

        def _source_rank(finding: "ResearchFinding") -> tuple[int, float]:
            sk = finding.source.domain
            standing = self._snapshot.get(sk)
            if standing is None or standing.observation.retired:
                return (1, 0.0)
            obs = standing.observation
            if obs.confidence < self._confidence_floor:
                return (1, 0.0)
            return (0, -obs.confidence)

        ranked = sorted(findings, key=_source_rank)
        return tuple(ranked)

    def weight_confidence(self, finding: "ResearchFinding") -> float:
        """Advisory adjusted confidence. Off/floored -> the finding's own confidence, unchanged."""
        if not self._consume_enabled:
            return finding.confidence
        sk = finding.source.domain
        standing = self._snapshot.get(sk)
        if standing is None or standing.observation.retired:
            return finding.confidence
        obs = standing.observation
        if obs.confidence < self._confidence_floor:
            return finding.confidence
        return round(finding.confidence * max(0.5, obs.confidence), 4)

    def as_observations(self, source_keys: tuple[str, ...]) -> tuple["Observation", ...]:
        """For Reasoning: reliability as Observations with Provenance(source='reliability')."""
        if not self._consume_enabled:
            return ()
        out: list[Observation] = []
        for sk in source_keys:
            standing = self._snapshot.get(sk)
            if standing is None:
                continue
            obs = standing.observation
            if obs.confidence < self._confidence_floor:
                continue
            trend_str = obs.trend.value
            note_txt = obs.note or f"trend={trend_str} confidence={obs.confidence:.2f}"
            out.append(Observation(
                statement=f"source {sk}: {note_txt}",
                provenance=ReasoningProvenance(source="reliability", ref=sk),
            ))
        return tuple(out)

    # ------------------------------------------------------------------ #
    # Internal: snapshot / journal                                         #
    # ------------------------------------------------------------------ #

    def _all_source_keys(self) -> list[str]:
        return list(self._snapshot.keys())

    def _load_snapshot(self) -> None:
        snapshot_path = Path(self._journal_dir) / "reliability.snapshot.json"
        if snapshot_path.exists():
            try:
                with open(snapshot_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sk, d in data.items():
                    prov = ReliabilityProvenance(
                        source_key=d["observation"]["provenance"]["source_key"],
                        supports=d["observation"]["provenance"]["supports"],
                        contradictions=d["observation"]["provenance"]["contradictions"],
                        window=d["observation"]["provenance"]["window"],
                        last_confirmed_at=d["observation"]["provenance"]["last_confirmed_at"],
                        evidence_events=tuple(d["observation"]["provenance"]["evidence_events"]),
                    )
                    obs = ReliabilityObservation(
                        source_key=d["observation"]["source_key"],
                        trend=ReliabilityTrend(d["observation"]["trend"]),
                        confidence=d["observation"]["confidence"],
                        freshness=d["observation"]["freshness"],
                        note=d["observation"]["note"],
                        provenance=prov,
                        retired=d["observation"].get("retired", False),
                    )
                    self._snapshot[sk] = SourceStanding(
                        source_key=d["source_key"],
                        version=d["version"],
                        observation=obs,
                        history_cap=d.get("history_cap", self._history_cap),
                    )
            except (json.JSONDecodeError, KeyError, ValueError):
                self._snapshot = {}

    def _persist_snapshot(self) -> None:
        Path(self._journal_dir).mkdir(parents=True, exist_ok=True)
        data: dict[str, dict[str, Any]] = {}
        for sk, standing in self._snapshot.items():
            obs = standing.observation
            data[sk] = {
                "source_key": standing.source_key,
                "version": standing.version,
                "history_cap": standing.history_cap,
                "observation": {
                    "source_key": obs.source_key,
                    "trend": obs.trend.value,
                    "confidence": obs.confidence,
                    "freshness": obs.freshness,
                    "note": obs.note,
                    "provenance": {
                        "source_key": obs.provenance.source_key,
                        "supports": obs.provenance.supports,
                        "contradictions": obs.provenance.contradictions,
                        "window": obs.provenance.window,
                        "last_confirmed_at": obs.provenance.last_confirmed_at,
                        "evidence_events": list(obs.provenance.evidence_events),
                    },
                    "retired": obs.retired,
                },
            }
        tmp = Path(self._journal_dir) / "reliability.snapshot.json.tmp"
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(Path(self._journal_dir) / "reliability.snapshot.json")

    def _rebuild(self, source_key: str) -> None:
        """Rebuild a single source's standing from the journal tail (bounded)."""
        all_records = self._store.all()
        entries = [
            e for e in all_records
            if e.get("source_key") == source_key and e.get("kind") == "outcome"
        ]
        recent = entries[-self._history_cap:] if entries else []
        supports = sum(1 for e in recent if e.get("validated") and not e.get("contradicted"))
        contradictions = sum(1 for e in recent if e.get("contradicted"))
        event_ids = tuple(e.get("event_id", "") for e in recent)
        last_confirmed = entries[-1]["timestamp"] if entries else _now()
        window = f"last_{len(recent)}_events"

        conf, freshness, trend = deterministic_confidence(
            supports, contradictions, last_confirmed
        )

        if source_key not in self._snapshot:
            version = 1
        else:
            version = self._snapshot[source_key].version + 1

        standing = self._snapshot.get(source_key)
        retired = standing.observation.retired if standing else False

        note = ""
        if trend == ReliabilityTrend.STALE:
            note = "freshness decayed; docs may lag releases"
        elif trend == ReliabilityTrend.UNRELIABLE:
            note = "contradictions dominate validated outcomes"
        elif trend == ReliabilityTrend.RELIABLE:
            note = "consistently validated"
        elif trend == ReliabilityTrend.MIXED:
            note = "inconclusive / balanced"

        evidence_events = event_ids
        if retired:
            evidence_events = evidence_events + ("retired",)

        prov = ReliabilityProvenance(
            source_key=source_key,
            supports=supports,
            contradictions=contradictions,
            window=window,
            last_confirmed_at=last_confirmed,
            evidence_events=evidence_events,
        )
        obs = ReliabilityObservation(
            source_key=source_key,
            trend=trend,
            confidence=conf,
            freshness=freshness,
            note=note,
            provenance=prov,
            retired=retired,
        )
        self._snapshot[source_key] = SourceStanding(
            source_key=source_key,
            version=version,
            observation=obs,
            history_cap=self._history_cap,
        )
        self._persist_snapshot()


# ===========================================================================
# Observation seam for Reasoning
# ===========================================================================

from ..reasoning.schema import Observation, Provenance as ReasoningProvenance  # noqa: E402
from .model import ResearchFinding  # noqa: E402
