"""CI reliability-eval-gate: prove consumption helps WITHOUT breaking coverage.

Runs the wider reliability benchmark (five source-behavior classes) off vs on and
exits non-zero unless the expanded adoption gate clears:
  - >=1 decision-quality axis improves (completion up / hallucination down)
  - citations held
  - reliability_usefulness > 0 (adopted reliability-guided choices measurably helped)
  - coverage identical off vs on (MANDATORY, one divergence = reject)
  - contradiction / freshness / recovery honesty axes above threshold
  - zero unsafe requests, zero authority increase, zero regressions

Enforcement plumbing only.  The reliability module, consumers, engines, and
tests are additive; no engine, perimeter, or schema code changes here.
Consumption stays default-off regardless of outcome -- this job only measures.
"""
from __future__ import annotations

import sys

from aetheris.research.reliability_benchmark import (
    ReliabilityEvalGate,
    run_reliability_benchmark,
)


def main() -> int:
    off = run_reliability_benchmark(False)
    on = run_reliability_benchmark(True)
    gate = ReliabilityEvalGate.evaluate(off, on)

    print("reliability eval gate")
    print(f"  completion:            off={off.completion:.3f}  on={on.completion:.3f}")
    print(f"  hallucination_rate:    off={off.hallucination_rate:.3f}  on={on.hallucination_rate:.3f}")
    print(f"  citation_correctness:  off={off.citation_correctness:.3f}  on={on.citation_correctness:.3f}")
    print(f"  reliability_usefulness: on={on.reliability_usefulness:.3f}")
    print(f"  coverage_identical:    on={on.coverage_identical}")
    print(f"  contradiction_handling:{on.contradiction_handling:.3f}")
    print(f"  freshness_discrimination:{on.freshness_discrimination:.3f}")
    print(f"  recovery_correctness:  {on.recovery_correctness:.3f}")
    print(f"  abstention_correctness:{on.abstention_correctness:.3f}")
    print(f"  unsafe_requests:       {on.unsafe_requests}")
    print(f"  authority_increase:    {on.authority_increase}")
    print(f"  regressions:           {on.regressions}")

    if not gate.adopt_default_on:
        print("BUILD FAILURE: reliability eval gate did not clear:")
        for reason in gate.reasons:
            print("  -", reason)
        return 1

    print("reliability eval gate: PASS")
    print("BUILD OK: reliability consumption measurably helps without changing coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
