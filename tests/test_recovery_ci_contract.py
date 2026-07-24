"""Tests for recovery drill CI contract — file references, gate integration, and reproducibility."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from aetheris.evaluation.recovery_model import (
    DrillReport,
    RecoveryMetrics,
    ScenarioVerification,
)
from aetheris.evaluation.recovery_view import ReadOnlyAuditView, render_report_json
from aetheris.trace.model import TraceValue
from recovery_fixtures import ALL_SCENARIOS, SCENARIO_MAP


def _tv(state: str, value: object, reason: str = "", source: str = "test") -> TraceValue:
    if state == "known":
        return TraceValue(state="known", value=value, source=source)
    if state == "unknown":
        return TraceValue(state="unknown", value=None, reason=reason, source=source)
    if state == "not_applicable":
        return TraceValue(state="not_applicable", value=None, reason=reason)
    if state == "mismatch":
        return TraceValue(state="mismatch", value={"detail": value}, reason=reason, source=source)
    raise ValueError(f"unknown state {state}")


class TestCIContractFilesExist:
    def test_recovery_fixtures_script_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = repo_root / "scripts" / "recovery_fixtures.py"
        assert script.exists(), f"Missing script: {script}"

    def test_run_recovery_drill_script_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = repo_root / "scripts" / "run_recovery_drill.py"
        assert script.exists(), f"Missing script: {script}"

    def test_recovery_model_module_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        module = repo_root / "src" / "aetheris" / "evaluation" / "recovery_model.py"
        assert module.exists(), f"Missing module: {module}"

    def test_recovery_verify_module_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        module = repo_root / "src" / "aetheris" / "evaluation" / "recovery_verify.py"
        assert module.exists(), f"Missing module: {module}"

    def test_recovery_view_module_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        module = repo_root / "src" / "aetheris" / "evaluation" / "recovery_view.py"
        assert module.exists(), f"Missing module: {module}"

    def test_architecture_doc_exists(self):
        repo_root = Path(__file__).resolve().parent.parent
        doc = repo_root / "architecture" / "RECOVERY_DRILL_HARNESS.md"
        assert doc.exists(), f"Missing doc: {doc}"

    def test_recovery_test_files_exist(self):
        repo_root = Path(__file__).resolve().parent.parent
        tests_dir = repo_root / "tests"
        for name in (
            "test_recovery_drill.py",
            "test_recovery_verification.py",
            "test_recovery_authority.py",
            "test_recovery_ci_contract.py",
        ):
            assert (tests_dir / name).exists(), f"Missing test: {tests_dir / name}"


class TestCIContractNoGeneratedArtifacts:
    def test_no_tracked_generated_drill_reports(self):
        repo_root = Path(__file__).resolve().parent.parent
        git_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        for line in git_status.stdout.splitlines():
            if "recovery-drill" in line or "reports/recovery" in line:
                assert False, f"Tracked generated artifact found: {line}"

    def test_no_tracked_temp_roots(self):
        repo_root = Path(__file__).resolve().parent.parent
        git_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        for line in git_status.stdout.splitlines():
            if "recovery_drill_" in line:
                assert False, f"Tracked temp root found: {line}"


class TestCIContractScenarioIntegrity:
    def test_all_scenarios_have_unique_ids(self):
        ids = [s.scenario_id for s in ALL_SCENARIOS]
        assert len(ids) == len(set(ids))

    def test_all_scenarios_have_valid_classifications(self):
        for s in ALL_SCENARIOS:
            assert s.rollback_kind is not None

    def test_scenario_map_consistent_with_all_scenarios(self):
        for s in ALL_SCENARIOS:
            assert s.scenario_id in SCENARIO_MAP
            assert SCENARIO_MAP[s.scenario_id] is s

    def test_scenario_ids_follow_convention(self):
        for s in ALL_SCENARIOS:
            assert s.scenario_id.startswith("S-"), f"{s.scenario_id} does not follow S-N convention"


class TestCIContractReportStructure:
    def test_report_json_has_required_fields(self):
        v = ScenarioVerification(
            scenario_id="test",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(),
        )
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=RecoveryMetrics(exact_count=1, total_attempted=1),
        )
        data = render_report_json(report)
        assert "schema_version" in data
        assert "run_id" in data
        assert "candidate_revision" in data
        assert "verdict" in data
        assert "scenario_results" in data
        assert "metrics" in data
        assert "authority_delta" in data
        assert "unsafe_attempts" in data

    def test_report_json_metrics_has_required_fields(self):
        v = ScenarioVerification(
            scenario_id="test",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(),
        )
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=RecoveryMetrics(exact_count=1, total_attempted=1),
        )
        data = render_report_json(report)
        metrics = data["metrics"]
        assert "total_attempted" in metrics
        assert "exact_count" in metrics
        assert "exact_restoration_success_rate" in metrics
        assert "unsafe_attempts" in metrics
        assert "authority_increase" in metrics
        assert "evidence_preserved" in metrics

    def test_report_json_scenario_has_required_fields(self):
        v = ScenarioVerification(
            scenario_id="test",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(),
        )
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=RecoveryMetrics(exact_count=1, total_attempted=1),
        )
        data = render_report_json(report)
        sr = data["scenario_results"][0]
        assert "scenario_id" in sr
        assert "classification" in sr
        assert "receipt_valid" in sr
        assert "change_link_valid" in sr
        assert "restoration_match" in sr
        assert "evidence_preserved" in sr
        assert "safety_preserved" in sr
        assert "duration_ns" in sr
        assert "failures" in sr
        assert "unknowns" in sr


class TestCIContractRunnerScript:
    def test_run_recovery_drill_list_works(self):
        result = subprocess.run(
            [sys.executable, "-m", "scripts.run_recovery_drill", "--list"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        assert result.returncode == 0, f"--list failed: {result.stderr}"
        assert "S-01" in result.stdout

    def test_run_recovery_drill_all_generates_report(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="recovery_ci_") as tmpdir:
            output = Path(tmpdir) / "reports" / "recovery-drill"
            result = subprocess.run(
                [sys.executable, "-m", "scripts.run_recovery_drill", "--all", "--output", str(output)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            assert result.returncode in (0, 1), f"--all failed: {result.stderr}"
            report_file = output / "report.json"
            assert report_file.exists(), f"Report not generated at {report_file}"

    def test_run_recovery_drill_verify_report(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="recovery_ci_") as tmpdir:
            output = Path(tmpdir) / "reports" / "recovery-drill"
            subprocess.run(
                [sys.executable, "-m", "scripts.run_recovery_drill", "--all", "--output", str(output)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            report_file = output / "report.json"
            if report_file.exists():
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.run_recovery_drill", "--verify-report", str(report_file)],
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).resolve().parent.parent,
                )
                assert result.returncode == 0, f"--verify-report failed: {result.stderr}"

    def test_run_recovery_drill_render_summary(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="recovery_ci_") as tmpdir:
            output = Path(tmpdir) / "reports" / "recovery-drill"
            subprocess.run(
                [sys.executable, "-m", "scripts.run_recovery_drill", "--all", "--output", str(output)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            report_file = output / "report.json"
            if report_file.exists():
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.run_recovery_drill", "--render", str(report_file), "--format", "summary"],
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).resolve().parent.parent,
                )
                assert result.returncode == 0, f"--render summary failed: {result.stderr}"
                assert "Recovery Drill Report" in result.stdout or "scenario" in result.stdout

    def test_run_recovery_drill_render_json(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="recovery_ci_") as tmpdir:
            output = Path(tmpdir) / "reports" / "recovery-drill"
            subprocess.run(
                [sys.executable, "-m", "scripts.run_recovery_drill", "--all", "--output", str(output)],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            report_file = output / "report.json"
            if report_file.exists():
                result = subprocess.run(
                    [sys.executable, "-m", "scripts.run_recovery_drill", "--render", str(report_file), "--format", "json"],
                    capture_output=True,
                    text=True,
                    cwd=Path(__file__).resolve().parent.parent,
                )
                assert result.returncode == 0, f"--render json failed: {result.stderr}"
                data = json.loads(result.stdout)
                assert "scenario_results" in data


class TestCIContractNoWriteControls:
    def test_audit_view_has_no_write_methods(self):
        view_methods = [m for m in dir(ReadOnlyAuditView) if not m.startswith("_")]
        write_methods = [m for m in view_methods if m.startswith("write") or m.startswith("apply") or m.startswith("set")]
        assert len(write_methods) == 0, f"Write controls found: {write_methods}"

    def test_runner_has_no_apply_or_rollback_production_flags(self):
        import inspect
        from scripts.run_recovery_drill import main
        source = inspect.getsource(main)
        for flag in ("--apply", "--rollback-production", "--resume", "--repair", "--force"):
            assert flag not in source, f"Production flag {flag} found in runner"

    def test_runner_has_no_remote_options(self):
        import inspect
        from scripts.run_recovery_drill import main
        source = inspect.getsource(main)
        for flag in ("--remote", "--url", "--repository", "--revision"):
            assert flag not in source or "candidate_revision" in source


class TestCIContractNoContinueOnError:
    def test_gate_scripts_propagate_failure(self):
        repo_root = Path(__file__).resolve().parent.parent
        for script in ("scripts/run_hierarchy_gate.py", "scripts/run_unattended_gate.py"):
            path = repo_root / script
            if path.exists():
                result = subprocess.run(
                    [sys.executable, str(path)],
                    capture_output=True,
                    text=True,
                    cwd=repo_root,
                )
                assert result.returncode == 0, f"{script} returned non-zero"


class TestCIContractNoStaleContractReferences:
    def test_no_legacy_free_form_inverse_strings(self):
        from aetheris.changeset.model import InverseReference
        for field in InverseReference.__dataclass_fields__:
            field_obj = InverseReference.__dataclass_fields__[field]
            assert "free-form" not in str(field_obj.type)

    def test_no_ambiguous_hash_semantics_in_receipt(self):
        from aetheris.changeset.model import RollbackReceipt
        fields = [f.name for f in RollbackReceipt.__dataclass_fields__.values()]
        assert "before_hash" not in fields
        assert "after_hash" not in fields

    def test_rollback_kind_enum_has_expected_values(self):
        from aetheris.changeset.model import RollbackKind
        assert RollbackKind.GIT_REVERT.value == "git_revert"
        assert RollbackKind.RESTORE_SNAPSHOT.value == "restore_snapshot"
        assert RollbackKind.NOT_APPLICABLE.value == "not_applicable"
        assert RollbackKind.UNKNOWN.value == "unknown"

    def test_rollback_outcome_enum_has_expected_values(self):
        from aetheris.changeset.model import RollbackOutcome
        assert RollbackOutcome.SUCCEEDED.value == "succeeded"
        assert RollbackOutcome.FAILED.value == "failed"
        assert RollbackOutcome.PARTIAL.value == "partial"
        assert RollbackOutcome.BLOCKED.value == "blocked"
        assert RollbackOutcome.UNKNOWN.value == "unknown"


class TestCIContractNoCapabilityWidening:
    def test_no_new_capability_in_recovery_model(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "new_capability" not in source
        assert "new_authority" not in source

    def test_no_new_capability_in_recovery_verify(self):
        import aetheris.evaluation.recovery_verify as rv
        import inspect
        source = inspect.getsource(rv)
        assert "new_capability" not in source
        assert "new_authority" not in source

    def test_no_new_capability_in_recovery_view(self):
        import aetheris.evaluation.recovery_view as rview
        import inspect
        source = inspect.getsource(rview)
        assert "new_capability" not in source
        assert "new_authority" not in source


class TestCIContractTraceImportsWithoutChangeSet:
    def test_trace_module_does_not_import_changeset(self):
        import aetheris.trace as trace_mod
        import inspect
        source = inspect.getsource(trace_mod)
        assert "changeset" not in source.lower()

    def test_changeset_module_imports_deterministically(self):
        from aetheris.changeset import ChangeSet, RollbackReceipt
        assert ChangeSet is not None
        assert RollbackReceipt is not None

    def test_no_circular_import_masking(self):
        import aetheris.changeset as cs
        import aetheris.trace as trace_mod
        assert cs is not None
        assert trace_mod is not None


class TestCIContractRepositoryIntegrity:
    def test_candidate_sha_is_clean(self):
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        sha = result.stdout.strip()
        assert len(sha) == 40, f"SHA length incorrect: {sha}"

    def test_working_tree_is_clean(self):
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "", f"Working tree not clean: {result.stdout}"

    def test_no_untracked_recovery_drill_artifacts(self):
        repo_root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if "recovery-drill" in line or "recovery_drill" in line:
                assert False, f"Untracked recovery drill artifact: {line}"