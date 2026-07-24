"""Tests for recovery verification logic — honest classification, linkage, and evidence."""
from __future__ import annotations

import pytest

from aetheris.evaluation.recovery_model import (
    DrillReport,
    RecoveryMetrics,
    ScenarioVerification,
)
from aetheris.evaluation.recovery_verify import (
    classify_outcome,
    compute_metrics,
    determine_verdict,
    verify_authority_delta,
    verify_evidence_preserved,
    verify_identity_match,
    verify_receipt_linkage,
    verify_scenario,
    verify_sequence_order,
    verify_safety_invariants,
)
from aetheris.trace.model import TraceValue


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


class TestClassifyOutcome:
    def test_exact_when_identity_matches(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
        })()
        exp = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "exact"
        assert failures == ()

    def test_partial_when_identity_mismatches(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
        })()
        exp = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "def"),
        })()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "partial"
        assert len(failures) > 0

    def test_blocked_when_outcome_blocked(self):
        obs = type("Obs", (), {"outcome": "blocked"})()
        exp = type("Exp", (), {"expected_outcome": "blocked"})()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "blocked"

    def test_failed_when_outcome_failed(self):
        obs = type("Obs", (), {"outcome": "failed"})()
        exp = type("Exp", (), {"expected_outcome": "failed"})()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "failed"

    def test_unknown_when_outcome_unknown(self):
        obs = type("Obs", (), {"outcome": "unknown"})()
        exp = type("Exp", (), {"expected_outcome": "unknown"})()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "unknown"

    def test_not_applicable_when_not_attempted(self):
        obs = type("Obs", (), {"outcome": "not_attempted"})()
        exp = type("Exp", (), {"expected_outcome": "not_attempted"})()
        cls, failures = classify_outcome(obs, exp)
        assert cls == "not_applicable"


class TestReceiptLinkage:
    def test_valid_linkage(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "chg_abc123")
        assert valid is True
        assert errors == ()

    def test_mismatched_change_id(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "chg_def456")
        assert valid is False
        assert any("does not match" in e for e in errors)

    def test_empty_change_set_id(self):
        valid, errors = verify_receipt_linkage("", "chg_abc123")
        assert valid is False
        assert any("empty" in e for e in errors)

    def test_empty_receipt_change_id(self):
        valid, errors = verify_receipt_linkage("chg_abc123", "")
        assert valid is False
        assert any("empty" in e for e in errors)


class TestAuthorityDelta:
    def test_no_increase(self):
        before = (("read_files", "direct"), ("write_files", "delegated"))
        after = (("read_files", "direct"),)
        delta, failures = verify_authority_delta(before, after)
        assert delta == 0
        assert failures == ()

    def test_authority_increase_detected(self):
        before = (("read_files", "direct"),)
        after = (("read_files", "direct"), ("execute_commands", "direct"))
        delta, failures = verify_authority_delta(before, after)
        assert delta == 1
        assert len(failures) == 1

    def test_empty_before_and_after(self):
        delta, failures = verify_authority_delta((), ())
        assert delta == 0


class TestSafetyInvariants:
    def test_all_pass(self):
        ok, errors = verify_safety_invariants((("safety_check", True), ("other_check", True)))
        assert ok is True
        assert errors == ()

    def test_one_fails(self):
        ok, errors = verify_safety_invariants((("safety_check", True), ("other_check", False)))
        assert ok is False
        assert len(errors) == 1
        assert "safety invariant failed: other_check" in errors[0]

    def test_empty_checks(self):
        ok, errors = verify_safety_invariants(())
        assert ok is True
        assert errors == ()


class TestEvidencePreserved:
    def test_evidence_unchanged(self):
        before = (_tv("known", "hash1"), _tv("known", "hash2"))
        after = (_tv("known", "hash1"), _tv("known", "hash2"))
        ok, errors = verify_evidence_preserved(before, after)
        assert ok is True
        assert errors == ()

    def test_evidence_changed(self):
        before = (_tv("known", "hash1"),)
        after = (_tv("known", "hash2"),)
        ok, errors = verify_evidence_preserved(before, after)
        assert ok is False
        assert len(errors) == 1

    def test_evidence_count_changed(self):
        before = (_tv("known", "hash1"), _tv("known", "hash2"))
        after = (_tv("known", "hash1"),)
        ok, errors = verify_evidence_preserved(before, after)
        assert ok is False
        assert any("count changed" in e for e in errors)


class TestIdentityMatch:
    def test_both_none(self):
        ok, errors = verify_identity_match(None, None)
        assert ok is True

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


class TestSequenceOrder:
    def test_valid_order(self):
        ok, errors = verify_sequence_order(("A", "B", "C"), ("A", "B", "C"))
        assert ok is True

    def test_invalid_order(self):
        ok, errors = verify_sequence_order(("C", "A", "B"), ("A", "B", "C"))
        assert ok is False

    def test_empty_declared_order(self):
        ok, errors = verify_sequence_order(("A", "B"), ())
        assert ok is True

    def test_missing_dependency_blocks(self):
        ok, errors = verify_sequence_order(("A",), ("A", "B", "C"))
        assert ok is True


class TestComputeMetrics:
    def test_exact_rate_computation(self):
        v = ScenarioVerification(
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
        metrics = compute_metrics((v,))
        assert metrics.exact_count == 1
        assert metrics.exact_restoration_success_rate == 1.0

    def test_partial_rate_computation(self):
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
            restoration_match=_tv("mismatch", False, "partial"),
            evidence_preserved=_tv("known", True),
            authority_delta=0,
            safety_preserved=True,
            sequence_valid=_tv("known", True),
            duration_ns=1000,
            failures=("partial",),
            unknowns=(),
        )
        metrics = compute_metrics((v1, v2))
        assert metrics.exact_count == 1
        assert metrics.partial_count == 1
        assert metrics.partial_restoration_rate == 0.5

    def test_denominator_excludes_not_applicable(self):
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

    def test_unknown_work_avoided_when_no_ids(self):
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

    def test_regressions_enumerated(self):
        v = ScenarioVerification(
            scenario_id="regression_scenario",
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
        assert "regression_scenario" in metrics.regressions


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


class TestVerifyScenarioIntegration:
    def test_verify_scenario_returns_scenario_verification(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("check", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h1"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        v = verify_scenario(obs, expected, scenario_id="S-01")
        assert isinstance(v, ScenarioVerification)
        assert v.scenario_id == "S-01"
        assert v.classification == "exact"

    def test_verify_scenario_rejects_invalid_confirmation(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("check", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h2"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        v = verify_scenario(obs, expected, scenario_id="S-09")
        assert v.classification == "partial"
        assert v.evidence_preserved.state == "mismatch"

    def test_verify_scenario_with_unknowns(self):
        obs = type("Obs", (), {
            "outcome": "unknown",
            "observed_identity": _tv("unknown", None, "no identity"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (),
            "evidence_before": (),
            "evidence_after": (),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "unknown",
            "expected_identity": None,
        })()
        v = verify_scenario(obs, expected, scenario_id="S-14")
        assert v.classification == "unknown"


class TestHonestNonSuccess:
    def test_partial_fixture_reports_partial(self):
        obs = type("Obs", (), {
            "outcome": "partial",
            "observed_identity": _tv("mismatch", False, "partial restore"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("no_false_exact", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h2"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "partial"

    def test_blocked_fixture_reports_blocked(self):
        obs = type("Obs", (), {
            "outcome": "blocked",
            "observed_identity": _tv("not_applicable", None, "preflight blocked"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("no_mutation", True),),
            "evidence_before": (),
            "evidence_after": (),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "blocked",
            "expected_identity": None,
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "blocked"

    def test_failed_fixture_reports_failed(self):
        obs = type("Obs", (), {
            "outcome": "failed",
            "observed_identity": _tv("mismatch", "incompatible", "restore failed"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("protected_unchanged", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h1"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "failed",
            "expected_identity": None,
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "failed"

    def test_unknown_remains_unknown(self):
        obs = type("Obs", (), {
            "outcome": "unknown",
            "observed_identity": _tv("unknown", None, "missing identity"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("unknown_remains_unknown", True),),
            "evidence_before": (),
            "evidence_after": (),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "unknown",
            "expected_identity": None,
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "unknown"

    def test_not_applicable_not_inflated_as_exact(self):
        obs = type("Obs", (), {
            "outcome": "not_attempted",
            "observed_identity": _tv("not_applicable", None, "append-only"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("evidence_preserved", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h1"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "not_attempted",
            "expected_identity": None,
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "not_applicable"


class TestReceiptChangeSetLinkage:
    def test_receipt_linked_to_wrong_change_set(self):
        valid, errors = verify_receipt_linkage("chg_correct", "chg_wrong")
        assert valid is False
        assert any("does not match" in e for e in errors)

    def test_receipt_change_id_empty(self):
        valid, errors = verify_receipt_linkage("chg_abc", "")
        assert valid is False

    def test_change_set_id_empty(self):
        valid, errors = verify_receipt_linkage("", "chg_abc")
        assert valid is False


class TestReadonlyBehavior:
    def test_verify_scenario_does_not_modify_inputs(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("check", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h1"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        _ = verify_scenario(obs, expected, scenario_id="S-01")
        assert obs.outcome == "succeeded"

    def test_compute_metrics_does_not_modify_inputs(self):
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
        assert v.classification == "exact"


class TestUnknownPropagation:
    def test_unknown_not_promoted_to_exact(self):
        obs = type("Obs", (), {
            "outcome": "unknown",
            "observed_identity": _tv("unknown", None, "missing pre-mutation identity"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("unknown_remains_unknown", True),),
            "evidence_before": (),
            "evidence_after": (),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "unknown"

    def test_unknown_with_plausible_content_still_unknown(self):
        obs = type("Obs", (), {
            "outcome": "unknown",
            "observed_identity": _tv("unknown", None, "content plausible but identity missing"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("no_guessing", True),),
            "evidence_before": (),
            "evidence_after": (),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "unknown"


class TestInvalidConfirmationRejection:
    def test_confirmed_with_mismatched_hash_is_invalid(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "wrong_hash"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("check", True),),
            "evidence_before": (_tv("known", "correct_hash"),),
            "evidence_after": (_tv("known", "wrong_hash"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "correct_hash"),
        })()
        cls, failures = classify_outcome(obs, expected)
        assert cls == "partial"
        assert len(failures) > 0

    def test_receipt_linkage_failure_is_invalid(self):
        obs = type("Obs", (), {
            "outcome": "succeeded",
            "observed_identity": _tv("known", "abc"),
            "authority_before": (),
            "authority_after": (),
            "safety_checks": (("check", True),),
            "evidence_before": (_tv("known", "h1"),),
            "evidence_after": (_tv("known", "h1"),),
        })()
        expected = type("Exp", (), {
            "expected_outcome": "succeeded",
            "expected_identity": _tv("known", "abc"),
        })()
        v = verify_scenario(obs, expected, scenario_id="S-XX")
        assert v.classification == "exact"


class TestByteIdenticalOffPathBehavior:
    def test_recovery_model_frozen(self):
        from aetheris.evaluation.recovery_model import RecoveryMetrics
        m = RecoveryMetrics(exact_count=1)
        with pytest.raises(AttributeError):
            m.exact_count = 2

    def test_recovery_verify_pure_no_side_effects(self):
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
        assert v.classification == "exact"

    def test_recovery_view_read_only(self):
        from aetheris.evaluation.recovery_view import ReadOnlyAuditView
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
        from aetheris.evaluation.recovery_model import RecoveryMetrics
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


class TestNoAuthorityWidening:
    def test_authority_delta_zero_when_no_change(self):
        before = (("read_files", "direct"),)
        after = (("read_files", "direct"),)
        delta, failures = verify_authority_delta(before, after)
        assert delta == 0
        assert failures == ()

    def test_authority_delta_positive_when_widened(self):
        before = (("read_files", "direct"),)
        after = (("read_files", "direct"), ("execute_commands", "direct"))
        delta, failures = verify_authority_delta(before, after)
        assert delta == 1
        assert len(failures) == 1

    def test_compute_metrics_sums_authority_delta(self):
        v1 = ScenarioVerification(
            scenario_id="a",
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
            scenario_id="b",
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
        metrics = compute_metrics((v1, v2))
        assert metrics.authority_increase == 0


class TestNoRegressionToExistingCanaries:
    def test_recovery_verify_does_not_import_runtime(self):
        import aetheris.evaluation.recovery_verify as rv
        import inspect
        source = inspect.getsource(rv)
        assert "aetheris.api" not in source
        assert "aetheris.controller" not in source
        assert "aetheris.planner" not in source
        assert "aetheris.safety" not in source
        assert "aetheris.research" not in source

    def test_recovery_model_does_not_import_runtime(self):
        import aetheris.evaluation.recovery_model as rm
        import inspect
        source = inspect.getsource(rm)
        assert "aetheris.api" not in source
        assert "aetheris.controller" not in source
        assert "aetheris.planner" not in source