"""CI contract: workflow contains independent lint/test/coverage/integrity jobs."""
from __future__ import annotations

import yaml


def test_ci_has_independent_jobs():
    with open(".github/workflows/ci.yml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    jobs = cfg.get("jobs", {})
    required = {"lint", "test", "coverage", "repository-integrity"}
    assert required.issubset(jobs.keys()), f"missing jobs: {required - jobs.keys()}"


def test_test_job_not_conditional_on_lint():
    with open(".github/workflows/ci.yml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    test_job = cfg.get("jobs", {}).get("test", {})
    assert "if" not in test_job.get("steps", [{}])[0], "test job must not be conditional on lint"


def test_reports_upload_on_failure():
    with open(".github/workflows/ci.yml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    test_job = cfg.get("jobs", {}).get("test", {})
    uploads = [s for s in test_job.get("steps", []) if s.get("uses", "").startswith("actions/upload-artifact")]
    assert uploads, "test job must upload artifacts"
    assert uploads[0].get("if", "") == "always()", "test reports must upload on failure"
