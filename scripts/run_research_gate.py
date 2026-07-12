"""CI regression guard for the Research Engine adoption gate.

Runs the offline-vs-research benchmark + the absolute adoption gate and exits
non-zero if the gate no longer passes.  This is enforcement plumbing only: the
fixtures, the perimeter rule set, and the gate thresholds are untouched.  A
failure here means a real regression (completion drop, hallucination rise,
citation below threshold, an authority increase, or a single unsafe request)
— never a flake, because the benchmark is hermetic (the default transport makes
zero real egress).
"""
from __future__ import annotations

import sys

from aetheris.research import compare, on, on_with_injected_unsafe_attempt
from aetheris.research.api import ResearchGate, run_benchmark


def main() -> int:
    base = run_benchmark(False)
    on_res = compare(research=on())
    gate = ResearchGate.evaluate(base, on_res)

    print("research adoption gate:", "PASS" if gate.adopt_default_on else "FAIL")
    print("off :", base)
    print("on  :", on_res)
    print("reasons:", gate.reasons)

    # Absolute clause: a single unsafe request must fail the gate.
    unsafe = compare(research=on_with_injected_unsafe_attempt())
    if unsafe.gate.adopt_default_on:
        print("BUILD FAILURE: unsafe request did not fail the gate (absolute clause).")
        return 1

    if not gate.adopt_default_on:
        print("BUILD FAILURE: research adoption gate did not pass.")
        return 1

    print("BUILD OK: research adoption gate passed; unsafe-request clause holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
