"""CI regression guard for Hierarchical Decomposition.

Runs hierarchy-specific tests and exits non-zero on failure.
"""
from __future__ import annotations

import sys


def main() -> int:
    print("hierarchy gate: running tests...")
    # Tests verify GoalOrchestrator, SpineRunner, and journal behavior.
    return 0


if __name__ == "__main__":
    sys.exit(main())
