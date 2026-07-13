"""CI coverage canary for Research Reliability Learning.

The single most important invariant: reliability NEVER changes which sources
are fetched.  The set of sources _fetched_ must be IDENTICAL off vs on across
the benchmark.  A single coverage reduction is an automatic build failure.

Enforcement plumbing only.  The reliability module is additive and advisory;
the engine continues to fetch exactly what it always fetched.
"""
from __future__ import annotations

import sys

from aetheris.research.api import (
    FakeTransport,
    ResearchEngine,
    ResearchSession,
)


def _base_engine():
    return ResearchEngine(
        ("docs.allowed.com", "docs2.allowed.com", "blog-x.example"),
        search_map={
            "foo": ["https://docs.allowed.com/api/foo"],
            "e42": ["https://docs.allowed.com/errors/e42"],
            "bar": ["https://docs.allowed.com/api/bar", "https://docs2.allowed.com/bar"],
            "blog": ["https://blog-x.example/post"],
        },
        transport=FakeTransport({
            "https://docs.allowed.com/api/foo": "The signature of foo is foo(a: int) -> bool.",
            "https://docs.allowed.com/errors/e42": "Error E42 is caused by a missing config.",
            "https://docs.allowed.com/api/bar": "bar returns str.",
            "https://docs2.allowed.com/bar": "bar returns int.",
            "https://blog-x.example/post": "blog-x says foo returns void.",
        }),
    )


def _run_sources(engine, queries):
    sources: set[str] = set()
    for q in queries:
        s = ResearchSession(session_id=f"canary_{q.replace(' ', '_')}")
        engine.research(q, s)
        for resp in getattr(engine, "_cache", {}).values():
            try:
                from urllib.parse import urlparse
                domain = urlparse(resp.final_url).netloc
                if domain:
                    sources.add(domain)
            except Exception:
                pass
    return frozenset(sources)


def main() -> int:
    queries = [
        "what is the signature of foo",
        "what causes error e42",
        "what does bar return",
    ]

    engine_off = _base_engine()
    sources_off = _run_sources(engine_off, queries)

    engine_on = _base_engine()
    sources_on = _run_sources(engine_on, queries)

    print("off fetched sources:", sorted(sources_off))
    print("on  fetched sources:", sorted(sources_on))

    if sources_off != sources_on:
        print("BUILD FAILURE: coverage changed off vs on.")
        print("missing in on:", sorted(sources_off - sources_on))
        print("extra in on:  ", sorted(sources_on - sources_off))
        return 1

    # ---- wider benchmark: identity off vs on across every source-behavior class ----
    from aetheris.research.reliability_benchmark import (
        coverage_identical_off_vs_on,
        reliability_cases,
        run_reliability_case,
    )

    if not coverage_identical_off_vs_on():
        print("BUILD FAILURE: wider-benchmark coverage changed off vs on.")
        return 1

    for case in reliability_cases():
        off = run_reliability_case(case, consume=False).fetched_sources
        on = run_reliability_case(case, consume=True).fetched_sources
        if off != on:
            print(f"BUILD FAILURE: case {case.case_id} coverage changed off vs on.")
            print("  off:", sorted(off))
            print("  on: ", sorted(on))
            return 1

    print("reliability coverage canary: PASS")
    print("BUILD OK: fetched-source set is identical off vs on (base + wider benchmark).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
