"""CI regression guard for Deliberative Reasoning default-on.

Runs the amplified benchmark + the unchanged 5-clause gate and exits non-zero
if the gate no longer passes.  This is enforcement plumbing only: the
fixtures, divergence preconditions, scoring, and gate thresholds are untouched.
A failure here means a real regression (completion drop, retries/repairs rise,
a decision axis fall, abstention below 0.8, usefulness non-positive, or
blocked/unsafe increase) — never a flake, because the benchmark is hermetic.
"""
from __future__ import annotations

import sys

from aetheris.reasoning.benchmark import (
    ReasoningComparison,
    amplified_benchmark,
)


def main() -> int:
    cases = amplified_benchmark(".")
    result = ReasoningComparison(".").run(cases)
    gate = result.gate
    print("reasoning default-on gate:", "PASS" if gate.adopt_default_on else "FAIL")
    print(result.gate.explanation)
    print("clauses:", gate.clauses)
    if not gate.adopt_default_on:
        print("BUILD FAILURE: reasoning default-on gate did not pass.")
        return 1
    print("BUILD OK: reasoning default-on gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
