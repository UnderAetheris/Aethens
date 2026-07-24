# Aetheris Recovery Drill & Rollback Verification Harness v0

**Architecture specification**  
**Milestone class:** Hermetic recovery measurement and rollback-evidence verification  
**Runtime capability change:** None  
**Runtime authority change:** None

---

## 1. Purpose

This harness proves that Aetheris can safely execute rollback and recovery mechanisms inside hermetic disposable fixtures, and that the resulting receipts match the expected restoration state.

It is a development/CI-only measurement harness, not a runtime recovery subsystem.

---

## 2. Placement

```text
src/aetheris/evaluation/
  recovery_model.py       # frozen drill result/metric models
  recovery_verify.py      # pure comparison and scoring
  recovery_view.py        # pure read-only rendering

scripts/
  run_recovery_drill.py   # bounded development/CI runner
  recovery_fixtures.py    # static scenario implementations

architecture/
  RECOVERY_DRILL_HARNESS.md   # this document

tests/
  test_recovery_drill.py
  test_recovery_verification.py
  test_recovery_authority.py
  test_recovery_ci_contract.py
  fixtures/recovery/      # immutable source templates only
```

No `src/aetheris/recovery/` package is created. No production `RecoveryEngine` exists.

---

## 3. Two-layer design

### 3.1 Development runner (bounded effects)

- Creates a temporary root directory
- Constructs static fixtures
- Applies fixture mutation
- Invokes one allowlisted fixture rollback mechanism
- Observes files/state
- Emits append-only drill evidence

### 3.2 Pure verifier/scorer (no authority)

- Validates ChangeSet and receipt
- Compares expected/observed identities
- Classifies outcome (exact, partial, blocked, failed, unknown, not_applicable, invalid)
- Computes metrics
- Renders read-only audit views

The verifier has no filesystem, process, network, model, tool, planner, or writer authority.

---

## 4. Data model

### 4.1 ExpectedRestoration

Specifies what a scenario expects:

- `scenario_id` — unique identifier
- `rollback_kind` — which rollback mechanism was attempted
- `eligible_for_exact_restoration` — whether exact restoration is expected
- `expected_identity` — the expected ObjectIdentity after restoration
- `expected_outcome` — succeeded, failed, partial, blocked, unknown, not_attempted
- `expected_unchanged_evidence` — evidence that must remain unchanged
- `expected_authority_delta` — expected change in authority (must be <= 0)
- `expected_safety_invariants` — safety checks that must remain true
- `expected_unknowns` — expected unknown codes

### 4.2 RollbackObservation

Captures what was actually observed during a drill:

- `scenario_id` — links to the scenario
- `change_set_id` — the ChangeSet this rollback targets
- `receipt_id` — the RollbackReceipt produced
- `observed_identity` — the identity observed after rollback
- `evidence_before` / `evidence_after` — evidence hashes before and after
- `authority_before` / `authority_after` — authority vectors
- `safety_checks` — per-invariant pass/fail
- `started_monotonic_ns` / `finished_monotonic_ns` — timing
- `work_units_reused` — duplicate work avoided (unknown if not tracked)
- `unknowns` — any TraceUnknowns encountered

### 4.3 ScenarioVerification

The result of comparing observation against expectation:

- `classification` — exact, partial, blocked, failed, unknown, not_applicable, invalid
- `receipt_valid` — whether the receipt passes structural validation
- `change_link_valid` — whether receipt.change_id matches the ChangeSet
- `restoration_match` — TraceValue indicating identity match
- `evidence_preserved` — TraceValue indicating evidence integrity
- `authority_delta` — integer count of authority dimensions increased
- `safety_preserved` — whether all safety invariants passed
- `sequence_valid` — whether multi-step ordering was correct
- `duration_ns` — monotonic nanoseconds for the scenario
- `failures` — tuple of failure descriptions
- `unknowns` — tuple of TraceUnknowns
- `implementation_class` — existing_subsystem_mechanism, fixture_protocol_implementation, pure_contract_case

### 4.4 DrillReport

Top-level result of a drill run:

- `schema_version` — always 1
- `run_id` — deterministic run identifier
- `candidate_revision` — git SHA of the code under test
- `scenario_results` — tuple of ScenarioVerification
- `metrics` — RecoveryMetrics
- `authority_delta` — total authority increase (must be 0)
- `unsafe_attempts` — count of unsafe effects (must be 0)
- `regressions` — tuple of regression scenario IDs
- `unknowns` — tuple of TraceUnknowns
- `verdict` — pass, hold, or reject

### 4.5 RecoveryMetrics

Aggregate statistics:

- Counts: exact, partial, blocked, failed, unknown, not_applicable, invalid
- Rates: exact_restoration_success_rate, partial_restoration_rate, blocked_rollback_rate, failed_rollback_rate, unknown_restoration_rate, invalid_claim_rate
- Timing: median_duration_ns, p95_duration_ns
- Duplicate work avoided (unknown if not tracked)
- Regressions, unsafe_attempts, authority_increase, evidence_preserved

---

## 5. Static scenario matrix

| Scenario | Rollback kind | Implementation class | Exact eligible | Expected outcome |
|---|---|---|---|---|
| S-01 | restore_snapshot | fixture_protocol_implementation | yes | succeeded |
| S-02 | git_revert | existing_subsystem_mechanism | yes | succeeded |
| S-03 | restore_snapshot | fixture_protocol_implementation | yes | succeeded |
| S-06 | config_disable | fixture_protocol_implementation | yes | succeeded |
| S-07 | resume_checkpoint | fixture_protocol_implementation | yes | succeeded |
| S-08 | discard_sandbox | fixture_protocol_implementation | yes | succeeded |
| S-09 | not_applicable | pure_contract_case | no | not_attempted |
| S-10 | restore_snapshot | fixture_protocol_implementation | no | partial |
| S-11 | restore_snapshot | fixture_protocol_implementation | no | partial |
| S-12 | restore_snapshot | fixture_protocol_implementation | no | blocked |
| S-13 | restore_snapshot | fixture_protocol_implementation | no | failed |
| S-14 | restore_snapshot | fixture_protocol_implementation | no | unknown |

---

## 6. Hermetic execution boundary

### 6.1 Fresh disposable root

Each scenario runs in a new temporary directory created outside the repository checkout.

### 6.2 Path containment

Before every file operation:
- Resolve the candidate path
- Reject absolute caller-supplied paths
- Reject `..` traversal
- Reject paths not contained under the scenario root
- Reject symlink/junction escape
- Do not follow symlinks for destructive operations

### 6.3 Checkout immutability

The harness makes zero source-tree changes. CI fails if `git status --porcelain` changes.

### 6.4 No live network

No HTTP clients, sockets, DNS, package installation, remote Git URLs, or model calls.

### 6.5 Sterile environment

Child process environment is an explicit allowlist. Proxy/credential/global Git state is excluded.

### 6.6 Bounded subprocesses

Only the Git-revert fixture may invoke `git`, with exact argv templates and `shell=False`.

### 6.7 Resource bounds

Maximum scenarios, files, bytes, subprocess duration, total duration, and journal size are enforced. Exceeding a bound is `blocked`.

### 6.8 Cleanup

Cleanup occurs after evidence capture. Cleanup failure is reported.

---

## 7. Verification rules

### 7.1 Receipt validation

For every attempted rollback:
1. Validate ChangeSet canonical ID and schema
2. Validate receipt canonical ID and schema
3. Require `receipt.change_id == change_set.change_id`
4. Require trace linkage match when both trace IDs are known
5. Require rollback target type, scope, and locator to match ChangeSet target
6. Require observed pre-rollback identity to match ChangeSet after identity
7. Require expected restoration identity to match ChangeSet before identity
8. Compute observed post-rollback identity independently
9. Compare algorithm, digest, object type, scope, locator, and version fields
10. Require verifier provenance and no required unknowns for exact confirmation
11. Verify evidence prefix/history preservation
12. Verify authority vector did not increase
13. Verify all safety invariants remained true
14. Verify receipt classification agrees with independent observation

### 7.2 Classification rules

- **exact**: observed identity matches expected identity, receipt is valid, evidence preserved, safety preserved
- **partial**: some components restored, others remain changed
- **blocked**: preflight prevented the rollback before any mutation
- **failed**: mechanism attempted and failed without changing protected state
- **unknown**: insufficient evidence to classify
- **not_applicable**: rollback kind is not applicable (e.g., append-only)
- **invalid**: receipt claims confirmed but evidence mismatches, or linkage fails

### 7.3 Multi-step verification

- Compute deterministic group ID from scenario/run context
- Declare dependencies before mutation
- Reject cycles and missing dependencies
- Execute rollback in reverse topological order
- Record sequence index and start/finish times
- Verify each receipt independently
- A group is exact only when every required exact-eligible component is exact
- One partial component makes the group partial
- A blocked dependency blocks dependent steps
- Failure after earlier successful steps remains partial/failed
- Unknown required evidence makes group status unknown or partial
- Never claim atomicity, transactionality, or automatic compensation

---

## 8. Read-only audit view

The `ReadOnlyAuditView` class provides:

- `scenarios()` — all scenario verifications
- `metrics()` — aggregate recovery metrics
- `verdict()` — overall pass/hold/reject
- `mismatches()` — scenarios with partial/invalid classification or identity mismatch
- `unknowns_list()` — scenarios with unknown outcomes
- `render_summary()` — text summary
- `render_json()` — structured JSON for CI consumption

No write controls are exposed.

---

## 9. Safety and rollback discipline

- Rollback may not weaken safety to restore availability
- Rollback may not add tools, widen allowlists, or raise budgets
- Append-only evidence must not be deleted or truncated
- Unknown remains unknown
- Multi-step rollback must not be treated as atomic unless proven
- No automatic recovery in production

---

## 10. Replay linkage

- Use trace/replay and ChangeSet context where available
- Do not execute rollback through replay
- Compare observed receipts and expected outcomes only
- All replayed views remain read-only

---

## 11. CI integration

The harness is invoked as an independent CI job after Phase 0 is clean:

```bash
python -m pytest \
  tests/test_recovery_drill.py \
  tests/test_recovery_verification.py \
  tests/test_recovery_authority.py \
  tests/test_recovery_ci_contract.py -q

python scripts/run_recovery_drill.py \
  --all \
  --output reports/recovery-drill

python scripts/run_recovery_drill.py \
  --verify-report reports/recovery-drill/latest/report.json

python scripts/check_architecture_integrity.py --check

test -z "$(git status --porcelain)"
```

---

## 12. What Aetheris can verify after v0

If accepted, Aetheris can verify in disposable fixtures that selected rollback mechanisms:

- restore exact known state when exact restoration is supported
- produce receipts linked to the correct ChangeSet and observed identities
- report partial, blocked, failed, unknown, and not-applicable outcomes honestly
- preserve append-only evidence
- preserve safety and avoid authority growth
- respect declared multi-step reverse dependency order
- leave the production checkout and runtime behavior untouched

It still cannot claim automatic production recovery, universal rollback support, transaction atomicity, or production reliability from fixture doubles.