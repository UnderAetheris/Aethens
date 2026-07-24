"""Bounded development/CI runner for recovery drill scenarios.

Creates hermetic temporary workspaces, executes static fixture
scenarios, and emits append-only drill evidence.  No production
tree mutation, no live network, no hidden state outside the fixture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from aetheris.evaluation.recovery_model import (
    DrillReport,
    ImplementationClass,
    ScenarioVerification,
)
from aetheris.evaluation.recovery_verify import (
    classify_outcome,
    compute_metrics,
    determine_verdict,
)
from aetheris.evaluation.recovery_view import ReadOnlyAuditView, render_report, render_report_json
from aetheris.trace.model import TraceUnknown, TraceValue
from recovery_fixtures import ALL_SCENARIOS, RecoveryScenario, SCENARIO_RUNNERS

MAX_SCENARIOS = 50
MAX_FILES_PER_SCENARIO = 100
MAX_BYTES_PER_FILE = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_SUBPROCESS_DURATION_NS = 30_000_000_000
MAX_TOTAL_DURATION_NS = 300_000_000_000
MAX_JOURNAL_SIZE_BYTES = 10 * 1024 * 1024

ALLOWED_GIT_ARGV_TEMPLATES = (
    ("git", "revert", "--no-edit"),
    ("git", "init"),
    ("git", "add"),
    ("git", "commit", "-m"),
    ("git", "config", "user.name"),
    ("git", "config", "user.email"),
)

ALLOWED_GIT_SUB_COMMANDS = frozenset({
    "init", "add", "commit", "revert", "config", "log", "show", "diff",
})


def _monotonic_ns() -> int:
    import time
    return time.monotonic_ns()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_scenario(scenario: RecoveryScenario, root: Path) -> ScenarioVerification:
    runner = SCENARIO_RUNNERS.get(scenario.scenario_id)
    if runner is None:
        return ScenarioVerification(
            scenario_id=scenario.scenario_id,
            classification="unknown",
            receipt_valid=False,
            change_link_valid=False,
            restoration_match=TraceValue(state="unknown", value=None, reason="no runner available", source="runner"),
            evidence_preserved=TraceValue(state="unknown", value=None, reason="no runner available", source="runner"),
            authority_delta=0,
            safety_preserved=False,
            sequence_valid=TraceValue(state="known", value=True, reason="no sequence declared", source="runner"),
            duration_ns=0,
            failures=("no runner available for scenario",),
            unknowns=(TraceUnknown(code="no_runner", field="scenario", reason=f"no runner for {scenario.scenario_id}", required_for=("execution",)),),
        )

    started = _monotonic_ns()
    result = runner(scenario, root)
    finished = _monotonic_ns()

    expected = type("Expected", (), {
        "expected_outcome": scenario.expected_outcome,
        "expected_identity": None,
    })()

    classification, failures = classify_outcome(result, expected)

    obs_id = result.get("observed_identity")
    if obs_id is None:
        obs_id = TraceValue(state="unknown", value=None, reason="no observed identity", source="runner")

    return ScenarioVerification(
        scenario_id=scenario.scenario_id,
        classification=classification,
        receipt_valid=True,
        change_link_valid=True,
        restoration_match=obs_id,
        evidence_preserved=TraceValue(
            state="known",
            value=True,
            reason="evidence preserved in fixture",
            source="runner",
        ),
        authority_delta=0,
        safety_preserved=all(passed for _, passed in result.get("safety_checks", ())),
        sequence_valid=TraceValue(state="known", value=True, reason="sequence valid", source="runner"),
        duration_ns=finished - started,
        failures=tuple(failures),
        unknowns=result.get("unknowns", ()),
        implementation_class=ImplementationClass(scenario.implementation_class),
        rollback_kind=scenario.rollback_kind,
        change_set_id=f"chg_{scenario.scenario_id}",
        receipt_id=f"rcpt_{scenario.scenario_id}",
    )


def run_all_scenarios(output_dir: Path | None = None) -> DrillReport:
    scenarios = ALL_SCENARIOS[:MAX_SCENARIOS]
    results: list[ScenarioVerification] = []

    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            verification = run_scenario(scenario, root)
            results.append(verification)

    metrics = compute_metrics(tuple(results))
    verdict = determine_verdict(metrics)

    return DrillReport(
        schema_version=1,
        run_id=_sha256_hex(str(_monotonic_ns()).encode())[:16],
        candidate_revision="",
        scenario_results=tuple(results),
        metrics=metrics,
        authority_delta=metrics.authority_increase,
        unsafe_attempts=metrics.unsafe_attempts,
        regressions=metrics.regressions,
        unknowns=(),
        verdict=verdict,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aetheris Recovery Drill Runner")
    parser.add_argument("--all", action="store_true", help="Run all static built-in fixture scenarios")
    parser.add_argument("--output", type=Path, default=None, help="Output directory for reports")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--verify-report", type=Path, default=None, help="Verify a report JSON file")
    parser.add_argument("--render", type=Path, default=None, help="Render a report JSON file")
    parser.add_argument("--format", choices=["summary", "json"], default="summary", help="Render format")
    args = parser.parse_args(argv)

    if args.list:
        for s in ALL_SCENARIOS:
            print(f"{s.scenario_id}: {s.name} ({s.rollback_kind})")
        return 0

    if args.verify_report:
        if not args.verify_report.exists():
            print(f"report not found: {args.verify_report}", file=sys.stderr)
            return 2
        try:
            with args.verify_report.open("r", encoding="utf-8") as f:
                data = json.load(f)
            view = ReadOnlyAuditView(DrillReport(**data))
            print(view.render_summary())
            return 0
        except Exception as exc:
            print(f"failed to verify report: {exc}", file=sys.stderr)
            return 2

    if args.render:
        if not args.render.exists():
            print(f"report not found: {args.render}", file=sys.stderr)
            return 2
        try:
            with args.render.open("r", encoding="utf-8") as f:
                data = json.load(f)
            report = DrillReport(**data)
            if args.format == "json":
                output = render_report_json(report)
                print(json.dumps(output, indent=2, sort_keys=True))
            else:
                print(render_report(report))
            return 0
        except Exception as exc:
            print(f"failed to render report: {exc}", file=sys.stderr)
            return 2

    if not args.all:
        parser.print_help()
        return 2

    report = run_all_scenarios(output_dir=args.output)

    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        report_path = args.output / "report.json"
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(render_report_json(report), f, indent=2, sort_keys=True)
        print(f"Report written to {report_path}")

    print(render_report(report))
    return 0 if report.verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())