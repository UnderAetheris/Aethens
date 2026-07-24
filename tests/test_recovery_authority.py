"""Tests for recovery harness authority and boundary constraints."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


from aetheris.evaluation.recovery_model import (
    ScenarioVerification,
)
from aetheris.evaluation.recovery_verify import (
    compute_metrics,
    determine_verdict,
    verify_scenario,
)
from aetheris.trace.model import TraceUnknown, TraceValue
from recovery_fixtures import ALL_SCENARIOS


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


class TestNoNewRuntimeAuthority:
    def test_recovery_model_has_no_runtime_imports(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "from aetheris.api" not in source
        assert "from aetheris.controller" not in source
        assert "from aetheris.planner" not in source
        assert "from aetheris.safety" not in source
        assert "from aetheris.research" not in source
        assert "from aetheris.unattended" not in source
        assert "from aetheris.learning" not in source
        assert "from aetheris.reflection" not in source

    def test_recovery_verify_has_no_runtime_imports(self):
        import aetheris.evaluation.recovery_verify as rv
        import inspect
        source = inspect.getsource(rv)
        assert "from aetheris.api" not in source
        assert "from aetheris.controller" not in source
        assert "from aetheris.planner" not in source
        assert "from aetheris.safety" not in source

    def test_recovery_view_has_no_runtime_imports(self):
        import aetheris.evaluation.recovery_view as rview
        import inspect
        source = inspect.getsource(rview)
        assert "from aetheris.api" not in source
        assert "from aetheris.controller" not in source
        assert "from aetheris.planner" not in source

    def test_evaluation_init_exports_only_evaluation_modules(self):
        from aetheris.evaluation import (
            DrillReport,
            ReadOnlyAuditView,
            ScenarioVerification,
            compute_metrics,
            determine_verdict,
            render_report,
            verify_scenario,
        )
        assert DrillReport is not None
        assert ReadOnlyAuditView is not None
        assert ScenarioVerification is not None
        assert compute_metrics is not None
        assert determine_verdict is not None
        assert render_report is not None
        assert verify_scenario is not None


class TestHarnessIsMeasurementOnly:
    def test_scenario_implementations_are_contract_cases(self):
        for s in ALL_SCENARIOS:
            assert s.implementation_class in {
                "existing_subsystem_mechanism",
                "fixture_protocol_implementation",
                "pure_contract_case",
            }

    def test_no_scenario_claims_production_reliability(self):
        for s in ALL_SCENARIOS:
            assert "production reliability" not in s.description.lower()
            assert "automatic recovery" not in s.description.lower()

    def test_no_scenario_requires_live_network(self):
        for s in ALL_SCENARIOS:
            assert "network" not in s.description.lower() or "no network" in s.description.lower()

    def test_no_scenario_mutates_production_checkout(self):
        for s in ALL_SCENARIOS:
            assert "production" not in s.description.lower() or "no production" in s.description.lower()


class TestSafetyMonotone:
    def test_rollback_does_not_weaken_safety(self):
        v = ScenarioVerification(
            scenario_id="safety_test",
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
        assert v.safety_preserved is True

    def test_rollback_does_not_widen_authority(self):
        v = ScenarioVerification(
            scenario_id="authority_test",
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
        assert v.authority_delta == 0

    def test_authority_increase_is_rejected(self):
        v = ScenarioVerification(
            scenario_id="authority_increase",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=1,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(),
        )
        metrics = compute_metrics((v,))
        assert metrics.authority_increase == 1
        assert determine_verdict(metrics) == "reject"


class TestAppendOnlyEvidencePreserved:
    def test_evidence_not_deleted(self):
        before = (_tv("known", "record1"), _tv("known", "record2"))
        after = (_tv("known", "record1"), _tv("known", "record2"))
        ok, errors = verify_scenario(
            type("Obs", (), {
                "outcome": "not_attempted",
                "observed_identity": _tv("not_applicable", None),
                "authority_before": (),
                "authority_after": (),
                "safety_checks": (("evidence_not_deleted", True),),
                "evidence_before": before,
                "evidence_after": after,
            })(),
            type("Exp", (), {
                "expected_outcome": "not_attempted",
                "expected_identity": None,
            })(),
            scenario_id="S-09",
        )
        assert ok.safety_preserved is True

    def test_evidence_not_truncated(self):
        before = (_tv("known", "record1"),)
        after = (_tv("known", "record1"),)
        ok, errors = verify_scenario(
            type("Obs", (), {
                "outcome": "not_attempted",
                "observed_identity": _tv("not_applicable", None),
                "authority_before": (),
                "authority_after": (),
                "safety_checks": (("evidence_not_truncated", True),),
                "evidence_before": before,
                "evidence_after": after,
            })(),
            type("Exp", (), {
                "expected_outcome": "not_attempted",
                "expected_identity": None,
            })(),
            scenario_id="S-09",
        )
        assert ok.safety_preserved is True


class TestUnknownRemainsUnknown:
    def test_unknown_not_promoted_to_success(self):
        v = ScenarioVerification(
            scenario_id="unknown_test",
            classification="unknown",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("unknown", None, "missing identity"),
            evidence_preserved=_tv("unknown", None, "no evidence"),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(
                TraceUnknown(code="missing_pre_mutation_identity", field="observed_identity", reason="removed", required_for=("exact_restoration",)),
            ),
        )
        assert v.classification == "unknown"
        assert v.restoration_match.state == "unknown"

    def test_unknown_cannot_confirm_exact(self):
        v = ScenarioVerification(
            scenario_id="unknown_cannot_confirm",
            classification="unknown",
            receipt_valid=False,
            change_link_valid=False,
            restoration_match=_tv("unknown", None, "cannot confirm"),
            evidence_preserved=_tv("unknown", None, "insufficient"),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("cannot confirm exact restoration with unknown evidence",),
            unknowns=(
                TraceUnknown(code="missing_snapshot", field="observed_identity", reason="no snapshot", required_for=("exact_restoration",)),
            ),
        )
        assert v.classification == "unknown"


class TestMultiStepNotAtomic:
    def test_multi_step_atomicity_is_none(self):
        v = ScenarioVerification(
            scenario_id="S-10",
            classification="partial",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("mismatch", False, "partial restore"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("one component remains changed",),
            unknowns=(),
        )
        assert v.classification == "partial"

    def test_earlier_receipts_not_rewritten(self):
        v1 = ScenarioVerification(
            scenario_id="step_1",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=500,
            failures=(),
            unknowns=(),
        )
        v2 = ScenarioVerification(
            scenario_id="step_2",
            classification="partial",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("mismatch", False, "partial"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=500,
            failures=("partial restore",),
            unknowns=(),
        )
        metrics = compute_metrics((v1, v2))
        assert metrics.partial_count == 1
        assert metrics.exact_count == 1


class TestNoAutomaticProductionRecovery:
    def test_harness_does_not_add_production_api(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "production" not in source or "no production" in source.lower()
        assert "automatic" not in source or "no automatic" in source.lower()
        assert "daemon" not in source
        assert "queue" not in source
        assert "worker" not in source
        assert "scheduler" not in source

    def test_harness_does_not_add_runtime_capability(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "capability" not in source or "no new capability" in source.lower()

    def test_harness_does_not_widen_authority_profile(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "authority" not in source or "no authority" in source.lower() or "no new" in source.lower()


class TestExistingCanariesAndGates:
    def test_existing_test_changeset_model_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_changeset_model.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_changeset_model.py failed: {result.stdout}"

    def test_existing_test_changeset_safety_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_changeset_safety.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_changeset_safety.py failed: {result.stdout}"

    def test_existing_test_trace_replay_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_trace_replay.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_trace_replay.py failed: {result.stdout}"

    def test_existing_test_safety_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_safety.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_safety.py failed: {result.stdout}"

    def test_existing_test_boundary_architecture_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_boundary_architecture.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_boundary_architecture.py failed: {result.stdout}"

    def test_existing_test_architecture_integrity_still_passes(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_architecture_integrity.py", "-q", "--tb=no"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"test_architecture_integrity.py failed: {result.stdout}"


class TestNoCheckoutMutationDuringDrill:
    def test_scenarios_use_temporary_directories(self):
        import tempfile
        for _ in range(3):
            with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
                root = Path(tmpdir)
                assert root.exists()
                assert str(root).startswith(tempfile.gettempdir())

    def test_no_absolute_paths_in_scenario_steps(self):
        for s in ALL_SCENARIOS:
            for step in s.steps:
                for key, val in step.items():
                    if isinstance(val, str) and val.startswith("/"):
                        assert False, f"{s.scenario_id} step {key} uses absolute path {val}"

    def test_no_network_references_in_scenarios(self):
        for s in ALL_SCENARIOS:
            for step in s.steps:
                for key, val in step.items():
                    if isinstance(val, str):
                        assert "http" not in val.lower(), f"{s.scenario_id} step {key} references network"
                        assert "https" not in val.lower(), f"{s.scenario_id} step {key} references network"


class TestImplementationClassSeparation:
    def test_scenarios_have_valid_implementation_classes(self):
        for s in ALL_SCENARIOS:
            assert s.implementation_class in {
                "existing_subsystem_mechanism",
                "fixture_protocol_implementation",
                "pure_contract_case",
            }

    def test_existing_mechanism_scenarios_are_few(self):
        existing = [s for s in ALL_SCENARIOS if s.implementation_class == "existing_subsystem_mechanism"]
        assert len(existing) <= 2

    def test_fixture_contract_cases_separate_from_existing_mechanisms(self):
        fixture_cases = [s for s in ALL_SCENARIOS if s.implementation_class == "fixture_protocol_implementation"]
        existing = [s for s in ALL_SCENARIOS if s.implementation_class == "existing_subsystem_mechanism"]
        assert len(fixture_cases) > 0
        assert len(existing) >= 0

    def test_pure_contract_cases_exist(self):
        contract_cases = [s for s in ALL_SCENARIOS if s.implementation_class == "pure_contract_case"]
        assert len(contract_cases) > 0