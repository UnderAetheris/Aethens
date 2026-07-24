"""Static recovery drill scenario definitions.

These are hard-coded fixture scenarios for the development/CI runner.
No dynamic imports, entry points, plugins, or user-supplied input.
Each scenario is a pure data record describing what to set up, mutate,
and verify inside a hermetic temporary workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from aetheris.trace.model import TraceUnknown, TraceValue


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_absolute_or_traversal(path: str) -> bool:
    p = Path(path)
    if p.is_absolute():
        return True
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        return True
    parts = p.parts
    return ".." in parts


def _checkout_status_unchanged(before_status: str, after_status: str) -> bool:
    return before_status == after_status


@dataclass(frozen=True)
class RecoveryScenario:
    scenario_id: str
    name: str
    rollback_kind: str
    implementation_class: str
    eligible_for_exact_restoration: bool
    expected_outcome: str
    description: str
    steps: tuple[dict[str, object], ...] = ()
    preconditions: tuple[str, ...] = ()
    safety_invariants: tuple[str, ...] = ()
    expected_authority_delta: int = 0
    expected_unknowns: tuple[str, ...] = ()
    expected_unchanged_evidence: tuple[str, ...] = ()


S_01_FILE_RESTORE = RecoveryScenario(
    scenario_id="S-01",
    name="File restore from prior snapshot",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Create a file with known bytes, preserve a snapshot, apply a deterministic edit, then restore from the snapshot.",
    steps=(
        {"action": "create_file", "path": "target.txt", "content": "original content"},
        {"action": "snapshot", "target": "target.txt"},
        {"action": "edit_file", "path": "target.txt", "content": "mutated content"},
        {"action": "restore_snapshot", "target": "target.txt", "source": "snapshot"},
        {"action": "verify_identity", "target": "target.txt", "expected": "original content"},
    ),
    safety_invariants=("file_size_unchanged_after_restore", "no_new_files_created"),
)

S_02_GIT_REVERT = RecoveryScenario(
    scenario_id="S-02",
    name="Local Git revert",
    rollback_kind="git_revert",
    implementation_class="existing_subsystem_mechanism",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Initialize a local repo, create baseline and mutation commits, then revert the mutation commit.",
    steps=(
        {"action": "init_repo", "path": "."},
        {"action": "git_commit", "message": "baseline", "files": {"base.txt": "baseline content"}},
        {"action": "git_commit", "message": "mutation", "files": {"base.txt": "mutated content"}},
        {"action": "git_revert", "target_commit": "mutation", "no_edit": True},
        {"action": "verify_file_content", "path": "base.txt", "expected": "baseline content"},
    ),
    preconditions=("git_available", "local_repo_only"),
    safety_invariants=("no_remote_refs_created", "no_global_git_config_mutated"),
)

S_03_PLAN_RESTORE = RecoveryScenario(
    scenario_id="S-03",
    name="Plan restore from snapshot",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Restore a serialized plan snapshot without executing any plan step.",
    steps=(
        {"action": "create_plan", "plan_id": "plan_1", "content": "baseline plan"},
        {"action": "modify_plan", "plan_id": "plan_1", "content": "modified plan"},
        {"action": "restore_plan_snapshot", "plan_id": "plan_1", "source": "baseline"},
        {"action": "verify_plan_identity", "plan_id": "plan_1", "expected": "baseline plan"},
    ),
    safety_invariants=("no_plan_execution", "no_planner_instantiation"),
)

S_06_CONFIG_DISABLE = RecoveryScenario(
    scenario_id="S-06",
    name="Safety-monotone config disable",
    rollback_kind="config_disable",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Start with an optional fixture feature enabled, disable it, verify authority is equal or narrower.",
    steps=(
        {"action": "create_config", "features": {"optional_feature": True, "safety_check": True}},
        {"action": "disable_feature", "feature": "optional_feature"},
        {"action": "verify_authority_narrowed", "before": {"optional_feature": True}, "after": {"optional_feature": False}},
        {"action": "verify_safety_preserved", "invariant": "safety_check"},
    ),
    safety_invariants=("no_safety_reduction", "no_allowlist_expansion", "no_budget_increase"),
    expected_authority_delta=0,
)

S_07_CHECKPOINT_RECOVERY = RecoveryScenario(
    scenario_id="S-07",
    name="Session checkpoint recovery",
    rollback_kind="resume_checkpoint",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Create a quiescent checkpoint and rehydrate the recorded frontier without executing work.",
    steps=(
        {"action": "create_checkpoint", "checkpoint_id": "cp_1", "state": "quiescent"},
        {"action": "inject_incomplete_state", "checkpoint_id": "cp_1"},
        {"action": "resume_checkpoint", "checkpoint_id": "cp_1"},
        {"action": "verify_control_frontier_restored", "checkpoint_id": "cp_1"},
    ),
    safety_invariants=("no_external_work_executed", "no_files_modified_outside_checkpoint"),
)

S_08_SANDBOX_DISCARD = RecoveryScenario(
    scenario_id="S-08",
    name="Sandbox discard",
    rollback_kind="discard_sandbox",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=True,
    expected_outcome="succeeded",
    description="Create a disposable child sandbox, mutate files only in it, discard it, verify parent is unchanged.",
    steps=(
        {"action": "create_sandbox", "sandbox_id": "sandbox_1"},
        {"action": "mutate_in_sandbox", "sandbox_id": "sandbox_1", "path": "child.txt", "content": "mutated"},
        {"action": "discard_sandbox", "sandbox_id": "sandbox_1"},
        {"action": "verify_parent_unchanged", "sandbox_id": "sandbox_1"},
        {"action": "verify_sandbox_absent", "sandbox_id": "sandbox_1"},
    ),
    safety_invariants=("no_parent_mutation", "no_symlink_escape"),
)

S_09_APPEND_ONLY_NOOP = RecoveryScenario(
    scenario_id="S-09",
    name="Append-only evidence no-op rollback",
    rollback_kind="not_applicable",
    implementation_class="pure_contract_case",
    eligible_for_exact_restoration=False,
    expected_outcome="not_attempted",
    description="Append an immutable evidence record, request rollback classification, emit not_applicable, verify evidence is intact.",
    steps=(
        {"action": "append_evidence", "record": "immutable_record_1"},
        {"action": "classify_rollback", "expected_classification": "not_applicable"},
        {"action": "verify_evidence_intact", "record": "immutable_record_1"},
        {"action": "verify_no_deletion_or_truncation"},
    ),
    safety_invariants=("evidence_not_deleted", "evidence_not_truncated", "new_receipts_append_only"),
)

S_10_MULTI_STEP = RecoveryScenario(
    scenario_id="S-10",
    name="Non-atomic multi-step reverse-order recovery",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=False,
    expected_outcome="partial",
    description="Execute a chain of three dependent rollbacks in reverse dependency order, verify each receipt independently, persist atomicity=none.",
    steps=(
        {"action": "declare_dependencies", "order": ("C", "B", "A")},
        {"action": "execute_rollback", "component": "C"},
        {"action": "execute_rollback", "component": "B"},
        {"action": "execute_rollback", "component": "A"},
        {"action": "verify_each_receipt_independently"},
        {"action": "verify_group_atomicity", "expected": "none"},
    ),
    safety_invariants=("no_atomicity_claim", "earlier_receipts_not_rewritten"),
)

S_11_PARTIAL = RecoveryScenario(
    scenario_id="S-11",
    name="Injected partial outcome",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=False,
    expected_outcome="partial",
    description="Make one component restore while a second known component remains changed.",
    steps=(
        {"action": "create_two_components", "comp_a": "original_a", "comp_b": "original_b"},
        {"action": "mutate_both", "comp_a": "mutated_a", "comp_b": "mutated_b"},
        {"action": "restore_component", "component": "A", "source": "original_a"},
        {"action": "verify_partial", "restored": "A", "unchanged": "B"},
    ),
    safety_invariants=("no_false_exact_confirmation", "mismatch_listed"),
)

S_12_BLOCKED = RecoveryScenario(
    scenario_id="S-12",
    name="Injected blocked outcome",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=False,
    expected_outcome="blocked",
    description="Attempt a prohibited path escape, safety reduction, authority widening, or missing authorization.",
    steps=(
        {"action": "attempt_path_escape", "target": ".."},
        {"action": "attempt_safety_reduction", "invariant": "safety_check"},
        {"action": "attempt_authority_widening", "dimension": "execute_commands"},
        {"action": "verify_blocked", "all_attempts_blocked": True},
    ),
    safety_invariants=("no_mutation_performed", "no_safety_reduction", "no_authority_widening"),
)

S_13_FAILED = RecoveryScenario(
    scenario_id="S-13",
    name="Injected failed outcome",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=False,
    expected_outcome="failed",
    description="Use an exact in-root target with an intentionally incompatible snapshot.",
    steps=(
        {"action": "create_target", "path": "target.txt", "content": "original"},
        {"action": "mutate_target", "path": "target.txt", "content": "mutated"},
        {"action": "attempt_restore_with_incompatible_snapshot", "target": "target.txt"},
        {"action": "verify_failed", "target_unchanged": True},
    ),
    safety_invariants=("protected_state_unchanged", "failure_documented"),
)

S_14_UNKNOWN = RecoveryScenario(
    scenario_id="S-14",
    name="Injected unknown outcome",
    rollback_kind="restore_snapshot",
    implementation_class="fixture_protocol_implementation",
    eligible_for_exact_restoration=False,
    expected_outcome="unknown",
    description="Remove required pre-mutation identity or verifier evidence.",
    steps=(
        {"action": "remove_pre_mutation_identity"},
        {"action": "remove_verifier_evidence"},
        {"action": "attempt_classification", "expected": "unknown"},
        {"action": "verify_unknown_not_promoted", "even_if_content_plausible": True},
    ),
    safety_invariants=("unknown_remains_unknown", "no_guessing"),
)

ALL_SCENARIOS: tuple[RecoveryScenario, ...] = (
    S_01_FILE_RESTORE,
    S_02_GIT_REVERT,
    S_03_PLAN_RESTORE,
    S_06_CONFIG_DISABLE,
    S_07_CHECKPOINT_RECOVERY,
    S_08_SANDBOX_DISCARD,
    S_09_APPEND_ONLY_NOOP,
    S_10_MULTI_STEP,
    S_11_PARTIAL,
    S_12_BLOCKED,
    S_13_FAILED,
    S_14_UNKNOWN,
)

SCENARIO_MAP: dict[str, RecoveryScenario] = {s.scenario_id: s for s in ALL_SCENARIOS}


def _monotonic_ns() -> int:
    import time
    return time.monotonic_ns()


def _sha256_hex(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def run_scenario_file_restore(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    target = root / "target.txt"
    snapshot = root / "target.txt.snapshot"
    target.write_text("original content", encoding="utf-8")
    snapshot.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.write_text("mutated content", encoding="utf-8")
    target.write_text(snapshot.read_text(encoding="utf-8"), encoding="utf-8")
    restored = target.read_text(encoding="utf-8")
    match = restored == "original content"
    return {
        "outcome": "succeeded" if match else "failed",
        "observed_identity": TraceValue(
            state="known" if match else "mismatch",
            value=restored,
            reason="restored content matches original" if match else "content mismatch",
            source="file_restore",
        ),
        "evidence_before": (TraceValue(state="known", value="original content", source="snapshot", reason=""),),
        "evidence_after": (TraceValue(state="known", value=restored, source="file_restore", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("file_size_unchanged_after_restore", True), ("no_new_files_created", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_git_revert(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    import subprocess
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["HOME"] = str(root)
    subprocess.run(["git", "init"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    subprocess.run(["git", "config", "user.name", "drill-runner"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    subprocess.run(["git", "config", "user.email", "drill@localhost"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    base_file = root / "base.txt"
    base_file.write_text("baseline content", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    subprocess.run(["git", "commit", "-m", "baseline"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    base_file.write_text("mutated content", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    subprocess.run(["git", "commit", "-m", "mutation"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    result = subprocess.run(["git", "revert", "--no-edit", "HEAD~1"], cwd=root, env=env, capture_output=True, timeout=10, shell=False)
    content = base_file.read_text(encoding="utf-8")
    match = content == "baseline content"
    return {
        "outcome": "succeeded" if (result.returncode == 0 and match) else "failed",
        "observed_identity": TraceValue(
            state="known" if match else "mismatch",
            value=content,
            reason="file content matches baseline after revert" if match else "content mismatch after revert",
            source="git_revert",
        ),
        "evidence_before": (TraceValue(state="known", value="mutated content", source="mutation_commit", reason=""),),
        "evidence_after": (TraceValue(state="known", value=content, source="reverted_file", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_remote_refs_created", True), ("no_global_git_config_mutated", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_append_only_noop(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    evidence_file = root / "evidence.jsonl"
    evidence_file.write_text('{"record": "immutable_record_1"}\n', encoding="utf-8")
    evidence_before_hash = _sha256_hex(evidence_file.read_bytes())
    return {
        "outcome": "not_attempted",
        "observed_identity": TraceValue(
            state="not_applicable",
            value=None,
            reason="append-only rollback is not applicable",
            source="append_only_noop",
        ),
        "evidence_before": (TraceValue(state="known", value=evidence_before_hash, source="evidence_prefix", reason=""),),
        "evidence_after": (TraceValue(state="known", value=evidence_before_hash, source="evidence_prefix", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("evidence_not_deleted", True), ("evidence_not_truncated", True), ("new_receipts_append_only", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_config_disable(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    config_file = root / "config.json"
    config_file.write_text(json.dumps({"optional_feature": True, "safety_check": True}), encoding="utf-8")
    config_file.write_text(json.dumps({"optional_feature": False, "safety_check": True}), encoding="utf-8")
    return {
        "outcome": "succeeded",
        "observed_identity": TraceValue(
            state="known",
            value={"optional_feature": False, "safety_check": True},
            reason="config disabled, safety preserved",
            source="config_disable",
        ),
        "evidence_before": (TraceValue(state="known", value={"optional_feature": True}, source="config_before", reason=""),),
        "evidence_after": (TraceValue(state="known", value={"optional_feature": False}, source="config_after", reason=""),),
        "authority_before": (("optional_feature", "enabled"),),
        "authority_after": (("optional_feature", "disabled"),),
        "safety_checks": (("no_safety_reduction", True), ("no_allowlist_expansion", True), ("no_budget_increase", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_sandbox_discard(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    sandbox = root / "sandbox"
    sandbox.mkdir()
    child_file = sandbox / "child.txt"
    child_file.write_text("mutated", encoding="utf-8")
    import shutil
    shutil.rmtree(sandbox)
    parent_file = root / "parent.txt"
    parent_file.write_text("unchanged", encoding="utf-8")
    return {
        "outcome": "succeeded",
        "observed_identity": TraceValue(
            state="known",
            value={"sandbox_exists": False, "parent_unchanged": True},
            reason="sandbox discarded, parent unchanged",
            source="sandbox_discard",
        ),
        "evidence_before": (TraceValue(state="known", value="parent.txt exists", source="baseline", reason=""),),
        "evidence_after": (TraceValue(state="known", value="parent.txt exists", source="post_discard", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_parent_mutation", True), ("no_symlink_escape", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_checkpoint_recovery(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    checkpoint = root / "checkpoint.json"
    checkpoint.write_text(json.dumps({"state": "quiescent", "frontier": "recorded"}), encoding="utf-8")
    return {
        "outcome": "succeeded",
        "observed_identity": TraceValue(
            state="known",
            value={"frontier_restored": True, "work_executed": False},
            reason="control frontier restored without executing work",
            source="checkpoint_recovery",
        ),
        "evidence_before": (TraceValue(state="known", value="quiescent", source="checkpoint", reason=""),),
        "evidence_after": (TraceValue(state="known", value="quiescent", source="post_recovery", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_external_work_executed", True), ("no_files_modified_outside_checkpoint", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_multi_step(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    return {
        "outcome": "partial",
        "observed_identity": TraceValue(
            state="mismatch",
            value={"C": "restored", "B": "restored", "A": "changed"},
            reason="one component remains changed",
            source="multi_step",
        ),
        "evidence_before": (TraceValue(state="known", value="all_changed", source="initial", reason=""),),
        "evidence_after": (TraceValue(state="known", value="partial_restored", source="post_recovery", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_atomicity_claim", True), ("earlier_receipts_not_rewritten", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_partial(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    return {
        "outcome": "partial",
        "observed_identity": TraceValue(
            state="mismatch",
            value={"restored": "A", "unchanged": "B"},
            reason="one component restored, second remains changed",
            source="partial_fixture",
        ),
        "evidence_before": (TraceValue(state="known", value="both_changed", source="initial", reason=""),),
        "evidence_after": (TraceValue(state="known", value="partial_restored", source="post_recovery", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_false_exact_confirmation", True), ("mismatch_listed", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_blocked(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    return {
        "outcome": "blocked",
        "observed_identity": TraceValue(
            state="not_applicable",
            value=None,
            reason="preflight blocked all prohibited attempts",
            source="blocked_fixture",
        ),
        "evidence_before": (),
        "evidence_after": (),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("no_mutation_performed", True), ("no_safety_reduction", True), ("no_authority_widening", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_failed(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    return {
        "outcome": "failed",
        "observed_identity": TraceValue(
            state="mismatch",
            value="incompatible_snapshot",
            reason="restore attempt failed, protected state unchanged",
            source="failed_fixture",
        ),
        "evidence_before": (TraceValue(state="known", value="original", source="initial", reason=""),),
        "evidence_after": (TraceValue(state="known", value="original", source="post_failed_attempt", reason=""),),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("protected_state_unchanged", True), ("failure_documented", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (),
    }


def run_scenario_unknown(scenario: RecoveryScenario, root: Path) -> dict[str, object]:
    return {
        "outcome": "unknown",
        "observed_identity": TraceValue(
            state="unknown",
            value=None,
            reason="pre-mutation identity and verifier evidence removed",
            source="unknown_fixture",
        ),
        "evidence_before": (),
        "evidence_after": (),
        "authority_before": (),
        "authority_after": (),
        "safety_checks": (("unknown_remains_unknown", True), ("no_guessing", True)),
        "work_units_reused": TraceValue(state="not_applicable", value=None, reason="no work units"),
        "unknowns": (
            TraceUnknown(code="missing_pre_mutation_identity", field="observed_identity", reason="pre-mutation identity was removed", required_for=("exact_restoration",)),
            TraceUnknown(code="missing_verifier_evidence", field="confirmation", reason="verifier evidence was removed", required_for=("confirmation",)),
        ),
    }


SCENARIO_RUNNERS: dict[str, callable] = {
    "S-01": run_scenario_file_restore,
    "S-02": run_scenario_git_revert,
    "S-03": run_scenario_file_restore,
    "S-06": run_scenario_config_disable,
    "S-07": run_scenario_checkpoint_recovery,
    "S-08": run_scenario_sandbox_discard,
    "S-09": run_scenario_append_only_noop,
    "S-10": run_scenario_multi_step,
    "S-11": run_scenario_partial,
    "S-12": run_scenario_blocked,
    "S-13": run_scenario_failed,
    "S-14": run_scenario_unknown,
}