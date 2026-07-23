"""CI regression guard for Hierarchical Decomposition.

Runs hierarchy-specific tests and exits non-zero on failure.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_hierarchy.py", "-q"],
        cwd=REPO_ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
