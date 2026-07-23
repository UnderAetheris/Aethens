"""CI regression guard for Unattended Supervisor.

Runs unattended-specific tests and exits non-zero on failure.
"""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_unattended.py", "-q"],
        cwd=REPO_ROOT,
    )
    return result.returncode


from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent


if __name__ == "__main__":
    sys.exit(main())
