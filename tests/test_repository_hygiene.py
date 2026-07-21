"""Repository hygiene: tracked paths must not contain runtime artifacts."""
from __future__ import annotations

import subprocess



FORBIDDEN_PATTERNS = (
    "node_modules/",
    ".env",
    "tmp_smoke",
    ".aetheris_data/",
    "wf_",
    "reasoning_off_events.jsonl",
    "reasoning_on_events.jsonl",
    "package-lock.json",
)


def _tracked_paths() -> set[str]:
    out = subprocess.check_output(["git", "ls-files"], text=True, encoding="utf-8")
    return {line.strip() for line in out.splitlines() if line.strip()}


def test_no_forbidden_runtime_artifacts_tracked():
    tracked = _tracked_paths()
    violations = [p for p in tracked if any(pat in p for pat in FORBIDDEN_PATTERNS)]
    assert not violations, f"forbidden tracked artifacts: {violations}"


def test_no_gitignore_contradiction():
    tracked = _tracked_paths()
    violations = [p for p in tracked if p.endswith(".pyc") or p.endswith(".pyo")]
    assert not violations, f"tracked Python cache files: {violations}"
