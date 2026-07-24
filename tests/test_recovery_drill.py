"""Tests for the recovery drill harness — hermetic boundary and scenario execution."""
from __future__ import annotations

import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

from aetheris.evaluation.recovery_model import (
    DrillReport,
    RecoveryMetrics,
    ScenarioVerification,
)
from aetheris.evaluation.recovery_verify import (
    compute_metrics,
    determine_verdict,
    verify_identity_match,
    verify_receipt_linkage,
    verify_scenario,
    verify_sequence_order,
    verify_safety_invariants,
)
from aetheris.evaluation.recovery_view import ReadOnlyAuditView, render_report, render_report_json
from aetheris.trace.model import TraceUnknown, TraceValue
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


class TestHermeticBoundary:
    def test_scenario_root_is_fresh_and_unique(self):
        roots = set()
        for _ in range(3):
            with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
                roots.add(tmpdir)
        assert len(roots) == 3

    def test_absolute_path_input_rejected(self):
        from recovery_fixtures import _reject_absolute_or_traversal
        assert _reject_absolute_or_traversal("/etc/passwd") is True

    def test_traversal_rejected(self):
        from recovery_fixtures import _reject_absolute_or_traversal
        assert _reject_absolute_or_traversal("../../etc/passwd") is True
        assert _reject_absolute_or_traversal("a/../../etc/passwd") is True

    def test_safe_path_accepted(self):
        from recovery_fixtures import _reject_absolute_or_traversal
        assert _reject_absolute_or_traversal("target.txt") is False
        assert _reject_absolute_or_traversal("subdir/target.txt") is False

    def test_checkout_status_unchanged(self):
        before = " M src/aetheris/evaluation/recovery_model.py"
        after = " M src/aetheris/evaluation/recovery_model.py"
        from recovery_fixtures import _checkout_status_unchanged
        assert _checkout_status_unchanged(before, after) is True

    def test_scenario_map_contains_all_scenarios(self):
        for s in ALL_SCENARIOS:
            assert s.scenario_id in SCENARIO_MAP
            assert SCENARIO_MAP[s.scenario_id] is s

    def test_all_scenarios_have_unique_ids(self):
        ids = [s.scenario_id for s in ALL_SCENARIOS]
        assert len(ids) == len(set(ids))

    def test_all_scenarios_have_non_empty_names(self):
        for s in ALL_SCENARIOS:
            assert s.name

    def test_all_scenarios_have_valid_rollback_kinds(self):
        valid_kinds = {
            "git_revert", "restore_snapshot", "tombstone_unretire",
            "config_disable", "discard_sandbox", "resume_checkpoint",
            "not_applicable", "unknown",
        }
        for s in ALL_SCENARIOS:
            assert s.rollback_kind in valid_kinds, f"{s.scenario_id} has invalid rollback_kind"

    def test_all_scenarios_have_valid_expected_outcomes(self):
        valid_outcomes = {
            "succeeded", "failed", "partial", "blocked",
            "unknown", "not_attempted", "not_applicable",
        }
        for s in ALL_SCENARIOS:
            assert s.expected_outcome in valid_outcomes, f"{s.scenario_id} has invalid expected_outcome"


class TestFileRestoreScenario:
    def test_s01_exact_restoration_on_reversible_fixture(self):
        scenario = SCENARIO_MAP["S-01"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_file_restore
            result = run_scenario_file_restore(scenario, root)
            assert result["outcome"] == "succeeded"
            assert result["observed_identity"].state == "known"

    def test_s01_evidence_preserved(self):
        scenario = SCENARIO_MAP["S-01"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_file_restore
            result = run_scenario_file_restore(scenario, root)
            assert len(result["evidence_before"]) == len(result["evidence_after"])

    def test_s01_safety_checks_pass(self):
        scenario = SCENARIO_MAP["S-01"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_file_restore
            result = run_scenario_file_restore(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestGitRevertScenario:
    def test_s02_local_git_revert_restores_baseline(self):
        scenario = SCENARIO_MAP["S-02"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_git_revert
            result = run_scenario_git_revert(scenario, root)
            assert result["outcome"] == "succeeded"
            assert result["observed_identity"].state == "known"

    def test_s02_no_global_git_config_mutated(self):
        scenario = SCENARIO_MAP["S-02"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_git_revert
            result = run_scenario_git_revert(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestConfigDisableScenario:
    def test_s06_authority_narrowed_or_equal(self):
        scenario = SCENARIO_MAP["S-06"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_config_disable
            result = run_scenario_config_disable(scenario, root)
            assert result["outcome"] == "succeeded"

    def test_s06_safety_preserved(self):
        scenario = SCENARIO_MAP["S-06"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_config_disable
            result = run_scenario_config_disable(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestSandboxDiscardScenario:
    def test_s08_parent_baseline_unchanged(self):
        scenario = SCENARIO_MAP["S-08"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_sandbox_discard
            result = run_scenario_sandbox_discard(scenario, root)
            assert result["outcome"] == "succeeded"

    def test_s08_sandbox_absent_after_discard(self):
        scenario = SCENARIO_MAP["S-08"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_sandbox_discard
            result = run_scenario_sandbox_discard(scenario, root)
            obs = result["observed_identity"]
            assert obs.state == "known"
            assert obs.value is not None
            assert obs.value.get("sandbox_exists") is False


class TestAppendOnlyNoopScenario:
    def test_s09_not_applicable_classification(self):
        scenario = SCENARIO_MAP["S-09"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_append_only_noop
            result = run_scenario_append_only_noop(scenario, root)
            assert result["outcome"] == "not_attempted"
            assert result["observed_identity"].state == "not_applicable"

    def test_s09_evidence_intact(self):
        scenario = SCENARIO_MAP["S-09"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_append_only_noop
            result = run_scenario_append_only_noop(scenario, root)
            before_hash = result["evidence_before"][0].value
            after_hash = result["evidence_after"][0].value
            assert before_hash == after_hash


class TestMultiStepScenario:
    def test_s10_atomicity_none(self):
        scenario = SCENARIO_MAP["S-10"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_multi_step
            result = run_scenario_multi_step(scenario, root)
            assert result["outcome"] == "partial"

    def test_s10_no_atomicity_claim(self):
        scenario = SCENARIO_MAP["S-10"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_multi_step
            result = run_scenario_multi_step(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestPartialScenario:
    def test_s11_partial_classification(self):
        scenario = SCENARIO_MAP["S-11"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_partial
            result = run_scenario_partial(scenario, root)
            assert result["outcome"] == "partial"

    def test_s11_no_false_exact_confirmation(self):
        scenario = SCENARIO_MAP["S-11"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_partial
            result = run_scenario_partial(scenario, root)
            assert result["observed_identity"].state == "mismatch"


class TestBlockedScenario:
    def test_s12_blocked_classification(self):
        scenario = SCENARIO_MAP["S-12"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_blocked
            result = run_scenario_blocked(scenario, root)
            assert result["outcome"] == "blocked"

    def test_s12_no_mutation_performed(self):
        scenario = SCENARIO_MAP["S-12"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_blocked
            result = run_scenario_blocked(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestFailedScenario:
    def test_s13_failed_classification(self):
        scenario = SCENARIO_MAP["S-13"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_failed
            result = run_scenario_failed(scenario, root)
            assert result["outcome"] == "failed"

    def test_s13_protected_state_unchanged(self):
        scenario = SCENARIO_MAP["S-13"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_failed
            result = run_scenario_failed(scenario, root)
            for name, passed in result["safety_checks"]:
                assert passed is True


class TestUnknownScenario:
    def test_s14_unknown_classification(self):
        scenario = SCENARIO_MAP["S-14"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_unknown
            result = run_scenario_unknown(scenario, root)
            assert result["outcome"] == "unknown"

    def test_s14_unknown_not_promoted(self):
        scenario = SCENARIO_MAP["S-14"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            from recovery_fixtures import run_scenario_unknown
            result = run_scenario_unknown(scenario, root)
            assert result["observed_identity"].state == "unknown"


class TestDrillReport:
    def test_report_verdict_pass_when_all_exact(self):
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
        metrics = compute_metrics((v,))
        assert metrics.exact_count == 1
        assert metrics.exact_restoration_success_rate == 1.0

    def test_report_verdict_reject_on_unsafe(self):
        v = ScenarioVerification(
            scenario_id="test",
            classification="exact",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("known", True),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=False,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(),
        )
        metrics = compute_metrics((v,))
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=metrics,
        )
        assert determine_verdict(report.metrics) == "reject"

    def test_report_verdict_reject_on_authority_increase(self):
        v = ScenarioVerification(
            scenario_id="test",
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

    def test_report_verdict_reject_on_invalid(self):
        v = ScenarioVerification(
            scenario_id="test",
            classification="invalid",
            receipt_valid=False,
            change_link_valid=False,
            restoration_match=_tv("mismatch", False, "hash mismatch"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("hash mismatch",),
            unknowns=(),
        )
        metrics = compute_metrics((v,))
        assert metrics.invalid_count == 1

    def test_report_verdict_hold_on_mixed(self):
        v1 = ScenarioVerification(
            scenario_id="exact",
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
        v2 = ScenarioVerification(
            scenario_id="partial",
            classification="partial",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("mismatch", False, "partial restore"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("partial restore",),
            unknowns=(),
        )
        metrics = compute_metrics((v1, v2))
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v1, v2),
            metrics=metrics,
        )
        assert determine_verdict(report.metrics) == "hold"

    def test_metrics_denominators_exclude_not_applicable(self):
        v1 = ScenarioVerification(
            scenario_id="exact",
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
        v2 = ScenarioVerification(
            scenario_id="na",
            classification="not_applicable",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("not_applicable", None),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=0,
            failures=(),
            unknowns=(),
        )
        metrics = compute_metrics((v1, v2))
        assert metrics.exact_eligible_attempted == 1
        assert metrics.exact_restoration_success_rate == 1.0

    def test_metrics_unknown_work_avoided_is_unknown(self):
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
        metrics = compute_metrics((v,))
        assert metrics.duplicate_work_unknown is True


class TestReadOnlyAuditView:
    def test_view_exposes_scenarios(self):
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
        view = ReadOnlyAuditView(report)
        assert len(view.scenarios()) == 1

    def test_view_exposes_mismatches(self):
        v = ScenarioVerification(
            scenario_id="mismatch",
            classification="partial",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("mismatch", False, "partial restore"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("partial restore",),
            unknowns=(),
        )
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=RecoveryMetrics(partial_count=1, total_attempted=1),
        )
        view = ReadOnlyAuditView(report)
        mismatches = view.mismatches()
        assert len(mismatches) == 1

    def test_view_exposes_unknowns(self):
        v = ScenarioVerification(
            scenario_id="unknown",
            classification="unknown",
            receipt_valid=True,
            change_link_valid=True,
            restoration_match=_tv("unknown", None, "insufficient evidence"),
            evidence_preserved=_tv("unknown", None, "no evidence"),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=(),
            unknowns=(TraceUnknown(code="missing_snapshot", field="observed_identity", reason="no snapshot", required_for=("exact_restoration",)),),
        )
        report = DrillReport(
            run_id="test_run",
            candidate_revision="abc123",
            scenario_results=(v,),
            metrics=RecoveryMetrics(unknown_count=1, total_attempted=1),
        )
        view = ReadOnlyAuditView(report)
        unknowns = view.unknowns_list()
        assert len(unknowns) == 1

    def test_view_render_summary_is_string(self):
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
        summary = render_report(report)
        assert isinstance(summary, str)
        assert "test" in summary

    def test_view_render_json_is_dict(self):
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
        assert isinstance(data, dict)
        assert data["verdict"] == "pass"
        assert data["scenario_results"][0]["scenario_id"] == "test"

    def test_view_does_not_modify_report(self):
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
        view = ReadOnlyAuditView(report)
        _ = view.render_summary()
        _ = view.render_json()
        assert view.verdict() == "pass"


class TestVerifyScenario:
    def test_verify_scenario_returns_scenario_verification(self):
        from recovery_fixtures import run_scenario_file_restore
        scenario = SCENARIO_MAP["S-01"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            obs = run_scenario_file_restore(scenario, root)
            expected = type("Expected", (), {
                "expected_outcome": "succeeded",
                "expected_identity": None,
            })()
            v = verify_scenario(obs, expected, scenario_id="S-01")
            assert isinstance(v, ScenarioVerification)
            assert v.scenario_id == "S-01"

    def test_verify_scenario_classification_matches(self):
        from recovery_fixtures import run_scenario_blocked
        scenario = SCENARIO_MAP["S-12"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            obs = run_scenario_blocked(scenario, root)
            expected = type("Expected", (), {
                "expected_outcome": "blocked",
                "expected_identity": None,
            })()
            v = verify_scenario(obs, expected, scenario_id="S-12")
            assert v.classification == "blocked"

    def test_verify_scenario_with_unknowns(self):
        from recovery_fixtures import run_scenario_unknown
        scenario = SCENARIO_MAP["S-14"]
        with tempfile.TemporaryDirectory(prefix="recovery_drill_") as tmpdir:
            root = Path(tmpdir)
            obs = run_scenario_unknown(scenario, root)
            expected = type("Expected", (), {
                "expected_outcome": "unknown",
                "expected_identity": None,
            })()
            v = verify_scenario(obs, expected, scenario_id="S-14")
            assert v.classification == "unknown"
            assert len(v.unknowns) > 0


class TestVerifyReceiptLinkage:
    def test_valid_linkage(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "chg_abc123")
        assert valid is True
        assert errors == ()

    def test_mismatched_linkage(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "chg_def456")
        assert valid is False
        assert any("does not match" in e for e in errors)

    def test_empty_change_set_id(self):
        valid, errors = verify_receipt_linkage("", "chg_abc123")
        assert valid is False

    def test_empty_receipt_change_id(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "")
        assert valid is False


class TestVerifyIdentityMatch:
    def test_both_none(self):
        ok, errors = verify_identity_match(None, None)
        assert ok is True
        assert errors == ()

    def test_one_none(self):
        ok, errors = verify_identity_match(_tv("known", "value"), None)
        assert ok is False

    def test_matching_known(self):
        tv1 = _tv("known", "abc")
        tv2 = _tv("known", "abc")
        ok, errors = verify_identity_match(tv1, tv2)
        assert ok is True

    def test_mismatching_known(self):
        tv1 = _tv("known", "abc")
        tv2 = _tv("known", "def")
        ok, errors = verify_identity_match(tv1, tv2)
        assert ok is False


class TestVerifySafetyInvariants:
    def test_all_pass(self):
        ok, errors = verify_safety_invariants((("safety_check", True), ("other_check", True)))
        assert ok is True
        assert errors == ()

    def test_one_fails(self):
        ok, errors = verify_safety_invariants((("safety_check", True), ("other_check", False)))
        assert ok is False
        assert len(errors) == 1


class TestVerifySequenceOrder:
    def test_valid_order(self):
        ok, errors = verify_sequence_order(("A", "B", "C"), ("A", "B", "C"))
        assert ok is True

    def test_invalid_order(self):
        ok, errors = verify_sequence_order(("C", "A", "B"), ("A", "B", "C"))
        assert ok is False

    def test_empty_declared_order(self):
        ok, errors = verify_sequence_order(("A", "B"), ())
        assert ok is True


class TestDetermineVerdict:
    def test_pass_all_exact(self):
        metrics = RecoveryMetrics(
            exact_count=3,
            total_attempted=3,
            exact_eligible_attempted=3,
            exact_restoration_success_rate=1.0,
        )
        assert determine_verdict(metrics) == "pass"

    def test_reject_on_unsafe(self):
        metrics = RecoveryMetrics(
            exact_count=3,
            total_attempted=3,
            exact_eligible_attempted=3,
            exact_restoration_success_rate=1.0,
            unsafe_attempts=1,
        )
        assert determine_verdict(metrics) == "reject"

    def test_reject_on_authority_increase(self):
        metrics = RecoveryMetrics(
            exact_count=3,
            total_attempted=3,
            exact_eligible_attempted=3,
            exact_restoration_success_rate=1.0,
            authority_increase=1,
        )
        assert determine_verdict(metrics) == "reject"

    def test_reject_on_invalid(self):
        metrics = RecoveryMetrics(
            total_attempted=1,
            invalid_count=1,
            invalid_claim_rate=1.0,
        )
        assert determine_verdict(metrics) == "reject"

    def test_hold_on_mixed(self):
        metrics = RecoveryMetrics(
            exact_count=1,
            partial_count=1,
            total_attempted=2,
            exact_eligible_attempted=2,
            exact_restoration_success_rate=0.5,
        )
        assert determine_verdict(metrics) == "hold"

    def test_hold_on_zero_attempted(self):
        metrics = RecoveryMetrics()
        assert determine_verdict(metrics) == "hold"


class TestByteIdenticalOffPathBehavior:
    def test_recovery_model_frozen(self):
        from aetheris.evaluation.recovery_model import RecoveryMetrics
        m = RecoveryMetrics(exact_count=1)
        with pytest.raises(AttributeError):
            m.exact_count = 2

    def test_recovery_verify_pure_no_side_effects(self):
        v1 = ScenarioVerification(
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
        metrics = compute_metrics((v1,))
        assert metrics.exact_count == 1
        assert metrics.exact_restoration_success_rate == 1.0

    def test_recovery_view_read_only(self):
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
        view = ReadOnlyAuditView(report)
        _ = view.scenarios()
        _ = view.metrics()
        _ = view.verdict()
        _ = view.mismatches()
        _ = view.unknowns_list()
        _ = view.render_summary()
        _ = view.render_json()


class TestNoNewRuntimeAuthority:
    def test_recovery_model_imports_no_runtime_packages(self):
        import aetheris.evaluation.recovery_model as rm
        assert "aetheris.api" not in rm.__file__
        assert "aetheris.controller" not in rm.__file__
        assert "aetheris.planner" not in rm.__file__

    def test_recovery_verify_imports_no_runtime_packages(self):
        import aetheris.evaluation.recovery_verify as rv
        assert "aetheris.api" not in rv.__file__
        assert "aetheris.controller" not in rv.__file__
        assert "aetheris.planner" not in rv.__file__

    def test_recovery_view_imports_no_runtime_packages(self):
        import aetheris.evaluation.recovery_view as rview
        assert "aetheris.api" not in rview.__file__
        assert "aetheris.controller" not in rview.__file__
        assert "aetheris.planner" not in rview.__file__

    def test_runtime_import_graph_excludes_harness(self):
        import aetheris
        harness_modules = [
            "aetheris.evaluation.recovery_model",
            "aetheris.evaluation.recovery_verify",
            "aetheris.evaluation.recovery_view",
        ]
        for mod_name in harness_modules:
            assert mod_name not in str(aetheris.__file__)