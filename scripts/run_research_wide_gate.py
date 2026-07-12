"""CI regression guard for the wider research benchmark + expanded adoption gate.

Runs the realistic + adversarial benchmark and the expanded gate (completion up,
hallucination down, citations correct, the three honesty axes above threshold,
usefulness > 0, zero regressions/authority/unsafe-requests) and exits non-zero if
the gate no longer passes. Enforcement plumbing only -- the fixtures, the honesty
scoring, and the gate thresholds are untouched. The benchmark is hermetic (zero
real egress), so a failure is a real regression, never a flake.
"""
from __future__ import annotations

import sys

from aetheris.research import compare_wide, on_with_injected_unsafe_attempt_wide
from aetheris.research.benchmark import WideResearchGate, run_wide_benchmark


def main() -> int:
    base = run_wide_benchmark(False)
    on_res = run_wide_benchmark(True)
    gate = WideResearchGate.evaluate(base, on_res)

    print("research wide adoption gate:", "PASS" if gate.adopt_default_on else "FAIL")
    print("off :", base)
    print("on  :", on_res)
    print("reasons:", gate.reasons)

    # Absolute clause: a single unsafe request must fail the gate.
    unsafe = compare_wide(research=on_with_injected_unsafe_attempt_wide())
    if unsafe.gate.adopt_default_on:
        print("BUILD FAILURE: unsafe request did not fail the gate (absolute clause).")
        return 1

    if not gate.adopt_default_on:
        print("BUILD FAILURE: research wide adoption gate did not pass.")
        return 1

    print("BUILD OK: research wide adoption gate passed; unsafe-request clause holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
