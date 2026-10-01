"""Shared pytest setup for the Aetheris test suite."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Recovery drill fixtures live in scripts/ (they are shared with the CLI runner).
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(_SCRIPTS_DIR))

# Depth of nested pytest sessions. Subprocess pytest runs inherit this, so
# meta-tests that re-run the whole suite can skip themselves when nested
# (depth > 1) instead of recursing without bound.
PYTEST_DEPTH_ENV = "AETHERIS_PYTEST_DEPTH"
os.environ[PYTEST_DEPTH_ENV] = str(int(os.environ.get(PYTEST_DEPTH_ENV, "0")) + 1)
