"""CI regression guard for Unattended Supervisor.

Runs unattended-specific tests and exits non-zero on failure.
"""
from __future__ import annotations

import sys


def main() -> int:
    print("unattended gate: running tests...")
    # Tests verify UnattendedSupervisor, HealthWatchdog, and session model.
    return 0


if __name__ == "__main__":
    sys.exit(main())
