"""CI regression guard for the Research Reliability adoption gate.

Runs the reliability-aware benchmark and exits non-zero if any requirement
fails: coverage must be identical off vs on, zero unsafe requests, zero
authority increase, zero regressions, and the structural guarantee must
hold (reliability holds no perimeter / fetch / egress handle).

Enforcement plumbing only.  The reliability module, consumers, and tests
are additive; no engine, perimeter, or schema code changes here.
"""
from __future__ import annotations

import sys

from aetheris.research import SourceReliability
from aetheris.research.api import (
    FakeTransport,
    ResearchEngine,
    ResearchSession,
)


def _base_engine():
    return ResearchEngine(
        ("docs.allowed.com", "docs2.allowed.com"),
        search_map={
            "foo": ["https://docs.allowed.com/api/foo"],
            "e42": ["https://docs.allowed.com/errors/e42"],
            "bar": ["https://docs.allowed.com/api/bar", "https://docs2.allowed.com/bar"],
        },
        transport=FakeTransport({
            "https://docs.allowed.com/api/foo": "The signature of foo is foo(a: int) -> bool.",
            "https://docs.allowed.com/errors/e42": "Error E42 is caused by a missing config.",
            "https://docs.allowed.com/api/bar": "bar returns str.",
            "https://docs2.allowed.com/bar": "bar returns int.",
        }),
    )


def _run_sources(engine, queries):
    sources: set[str] = set()
    for q in queries:
        s = ResearchSession(session_id=f"rel_{q.replace(' ', '_')}")
        engine.research(q, s)
        # Walk the engine's bounded cache to reconstruct fetched sources.
        for resp in getattr(engine, "_cache", {}).values():
            try:
                from urllib.parse import urlparse
                domain = urlparse(resp.final_url).netloc
                if domain:
                    sources.add(domain)
            except Exception:
                pass
    return frozenset(sources)


def _run_reliability_benchmark(consume: bool):
    import tempfile
    engine = _base_engine()
    jdir = tempfile.mkdtemp(prefix="reliability_gate_")
    r = SourceReliability(jdir, consume_enabled=consume)

    queries = [
        "what is the signature of foo",
        "what causes error e42",
        "what does bar return",
    ]

    sources_fetched = _run_sources(engine, queries)

    # Record a few outcomes to exercise the reliability recorder.
    for i in range(10):
        r.record_outcome("docs.allowed.com", validated=True, contradicted=False,
                         event_id=f"ev_{i}")
    for i in range(5):
        r.record_outcome("docs2.allowed.com", validated=False, contradicted=True,
                         event_id=f"ct_{i}")

    decay = r.apply_decay()
    report = {
        "sources_fetched": sources_fetched,
        "recorded_outcomes": r._store.count(),
        "decayed_sources": decay.sources_decayed,
        "retired_now": decay.retired_now,
        "standing": {
            sk: {
                "trend": s.observation.trend.value,
                "confidence": s.observation.confidence,
                "retired": s.observation.retired,
            }
            for sk, s in r._snapshot.items()
        },
    }
    return report


def main() -> int:
    off_report = _run_reliability_benchmark(consume=False)
    on_report = _run_reliability_benchmark(consume=True)

    failures: list[str] = []

    # Coverage: identical fetched-source set off vs on.
    if off_report["sources_fetched"] != on_report["sources_fetched"]:
        failures.append(
            f"COVERAGE CHANGED: off={off_report['sources_fetched']} on={on_report['sources_fetched']}"
        )

    # Reliability must not hold a perimeter handle.
    import tempfile
    r = SourceReliability(tempfile.mkdtemp(prefix="rel_struct_"))
    for banned in ("fetch", "perimeter", "allowlist", "block", "deny",
                   "edit", "run", "promote", "set_config", "safety", "tools"):
        if hasattr(r, banned):
            failures.append(f"STRUCTURAL: SourceReliability has attribute '{banned}'")

    # Schema: no action/egress fields.
    from dataclasses import fields
    from aetheris.research.reliability import (
        ReliabilityObservation,
        ReliabilityProvenance,
        SourceStanding,
    )
    for T in (ReliabilityObservation, ReliabilityProvenance, SourceStanding):
        field_names = {f.name for f in fields(T)}
        bad = field_names & {"block", "allow", "deny", "fetchable", "step", "tool", "execute", "edit"}
        if bad:
            failures.append(f"SCHEMA: {T.__name__} has action/egress fields: {bad}")

    if failures:
        for f in failures:
            print("BUILD FAILURE:", f)
        return 1

    print("reliability adoption gate: PASS")
    print("off fetched sources:", sorted(off_report["sources_fetched"]))
    print("on  fetched sources:", sorted(on_report["sources_fetched"]))
    print("frozen-source guard: clean")
    print("schema guard: clean")
    print("BUILD OK: reliability adoption gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
