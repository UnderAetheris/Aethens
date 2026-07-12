"""CI regression guard for the Research NetworkPerimeter hardening suite.

Runs the adversarial perimeter + structural test file and exits non-zero if any
test fails. This is the permanent, teeth-on-safety guard: a future refactor that
quietly weakens a perimeter rule (allowlist, HTTPS, redirect cap, budgets, MIME,
robots, no auth/cookies/JS, dry-run, task-scope) or the absolute unsafe-request
clause fails the build. Zero real egress; deterministic.
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_research_hardening.py",
         "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": os.path.join(root, "src")},
    )
    if result.returncode != 0:
        print("BUILD FAILURE: research perimeter hardening suite did not pass.")
        return 1
    print("BUILD OK: research perimeter hardening suite passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
