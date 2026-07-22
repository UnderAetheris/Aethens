# Aetheris ChangeSet & Rollback Receipt Contract v0 — Implementation Report

## A. Revision and Scope

- **Base revision:** `31704237fd52ae7738ffd8d5f615f6fd48880713`
- **Worktree:** main branch
- **New capability added:** none
- **Authority change:** none

---

## B. Files Changed

| File | Action | Reason |
| --- | --- | --- |
| `src/aetheris/changeset/__init__.py` | **Added** | Package init; re-exports public API |
| `src/aetheris/changeset/model.py` | **Added** | ChangeSet, RollbackReceipt, ChangeKind, RollbackKind frozen models |
| `src/aetheris/changeset/canonical.py` | **Added** | Canonical JSON, hashing, deterministic change_id/receipt_id derivation |
| `src/aetheris/changeset/view.py` | **Added** | Read-only ChangeSetView and RollbackReceiptView |
| `src/aetheris/trace/adapters.py` | **Modified** | Added ChangeSetAdapter and RollbackReceiptAdapter; conditional import to preserve trace-replay independence |
| `src/aetheris/trace/replay.py` | **Modified** | Added `reduce_change_set_summary` and `reduce_rollback_summary` reducers |
| `scripts/inspect_trace.py` | **Modified** | Added `change_set=` and `rollback_receipt=` source kinds |
| `tests/test_changeset.py` | **Added** | 21 tests covering models, canonicalization, views, adapters, replay linkage |
| `architecture/CHANGESET_ROLLBACK_RECEIPT_CONTRACT.md` | **Added** | Architecture spec, invariants, integration points, evaluation strategy |
| `TRACE_REPLAY_IMPLEMENTATION_REPORT.md` | **Modified** | Addendum for changeset milestone |

---

## C. Model Contract

### ChangeSet fields
- `change_id`: deterministic ID derived from `subsystem|capability_id|change_kind|before_hash|after_hash|created_at`
- `trace_id`, `task_id`, `session_id`, `plan_id`: linkage to existing trace context
- `capability_id`, `subsystem`: owner attribution
- `change_kind`: one of 16 declared kinds (no broad wildcard)
- `before_hash`, `after_hash`: SHA-256 of exact byte representation before and after mutation
- `before_ref`, `after_ref`: `TraceValue` carriers referencing snapshot, journal line, config field, or evidence artifact
- `inverse_operation`: descriptive string naming the declared reverse action (never executed)
- `rollback_token`: opaque correlation string for existing subsystem rollback mechanisms
- `revision`, `config_fingerprint`, `evidence_refs`: context linkage
- `authority_class`: from existing `architecture/authority.json` boundary IDs
- `provenance`: origin, derivation rule, confidence
- `unknowns`: typed `TraceUnknown` entries for missing required facts
- `created_at`: timestamp as `TraceValue`

### RollbackReceipt fields
- `receipt_id`: deterministic ID derived from `change_id|rollback_kind|before_hash|after_hash|created_at`
- `change_id`: links back to the rolled-back change set
- `rollback_kind`: one of 8 declared kinds
- `rollback_target`, `rollback_outcome`, `confirmed_restored_state`: `TraceValue` carriers
- `before_hash`, `after_hash`: hash linkage to the change-set record
- `revision`, `config_fingerprint`, `evidence_refs`: context linkage
- `provenance`, `unknowns`, `created_at`: same pattern as ChangeSet

---

## D. Trace Integration

### Adapters
- `ChangeSetAdapter` (`adapter_id="change_set"`) projects `change_set` store records into `TraceEnvelope`
- `RollbackReceiptAdapter` (`adapter_id="rollback_receipt"`) projects `rollback_receipt` store records into `TraceEnvelope`

Both adapters are conditionally registered. The trace package imports do not fail if the changeset package is absent.

### Replay reducers
- `reduce_change_set_summary`: populates `state["change_kind_counts"]` and `state["change_capabilities"]`
- `reduce_rollback_summary`: populates `state["rollback_kind_counts"]`

### Lineage
- ChangeSet envelopes carry `trace_id` when supplied
- RollbackReceipt envelopes carry `change_id` in their record; causal edges can be constructed explicitly by trace consumers

---

## E. Authority Neutrality

- **New capability added:** none
- **Authority grant delta:** 0
- **Trace package imports:** no SafetyLayer, NetworkPerimeter, planner, executive, tools, config mutator, store writer, or model provider
- **ChangeSet package imports:** only standard library + `aetheris.trace.model`
- **Side-effect scan:** changeset package contains no write/process/network calls
- **Runtime import graph:** `aetheris.changeset` is not imported by any runtime module

---

## F. Tests Added

| Test | What it verifies |
| --- | --- |
| `test_change_set_creation` | ChangeSet can be created with all fields |
| `test_change_set_frozen` | ChangeSet is immutable |
| `test_change_kind_values` | Enum string values |
| `test_receipt_creation` | RollbackReceipt can be created with all fields |
| `test_rollback_kind_values` | Enum string values |
| `test_receipt_frozen` | RollbackReceipt is immutable |
| `test_stable_across_key_order` | Canonical JSON is deterministic |
| `test_deterministic_hash` | Same input produces same hash |
| `test_different_inputs_different_hash` | Different inputs produce different hashes |
| `test_deterministic` | Same ChangeSet produces same change_id |
| `test_different_before_hash` | Different before_hash produces different change_id |
| `test_deterministic` | Same RollbackReceipt produces same receipt_id |
| `test_different_change_id` | Different change_id produces different receipt_id |
| `test_render_summary` | ChangeSetView produces readable summary |
| `test_to_dict` | ChangeSetView produces correct dict |
| `test_render_summary` | RollbackReceiptView produces readable summary |
| `test_view_summary` | RollbackReceiptView summary contains change_id |
| `test_changeset_adapter_supports` | Adapter matches correct store kind |
| `test_changeset_adapter_project` | Adapter projects record into TraceEnvelope |
| `test_rollback_receipt_adapter_project` | Adapter projects record into TraceEnvelope |
| `test_change_set_envelope_in_replay` | ChangeSet envelope participates in replay and reducer |

Total: 21 new tests. All pass.

---

## G. Verification Results

| Command | Exit | Passed | Failed | Notes |
| --- | ---: | ---: | ---: | --- |
| `pytest tests/test_trace_*` | 0 | 36 | 0 | All green |
| `pytest tests/test_changeset.py` | 0 | 21 | 0 | All green |
| `pytest` (targeted regression) | 0 | 234 | 0 | Safety, tools, controller, planner, executive, research, hierarchy, unattended, reasoning, reflection, learning, experience, knowledge, skills, model |
| `ruff check .` | 0 | — | — | All green |
| `check_architecture_integrity.py --check` | 0 | — | — | PASSED |
| `run_reasoning_gate.py` | 0 | — | — | PASS |
| `run_research_gate.py` | 0 | — | — | PASS |
| `run_hierarchy_gate.py` | 0 | — | — | PASS |
| `run_unattended_gate.py` | 0 | — | — | PASS |

---

## H. Behavioral Neutrality

- Existing runtime does not import `aetheris.changeset`
- Trace package conditionally imports changeset; no failure if absent
- All existing tests pass without modification
- No runtime artifact bytes change when changeset package is unused

---

## I. Known Limitations

- Change sets are optional; subsystems must opt in to emit them
- Before/after refs are `TraceValue` carriers; exact reference semantics depend on the emitting subsystem
- Rollback receipts do not verify rollback success automatically; `confirmed_restored_state` must be supplied by the executing subsystem
- Cross-change-set ordering is derived from `created_at`; no causal edges are inferred automatically
- Multi-step rollback chains require explicit `change_id` linkage by the emitting subsystem

---

## J. Verdict

**PASS**

- Meaningful mutations can be described as change sets.
- Rollbacks can be described as receipts linked to those change sets.
- The system can explain what changed, what was reverted, and what restored state was confirmed.
- No new runtime authority is introduced.
- Existing behavior remains unchanged when unused.

This milestone is ready for the next step: **subsystem opt-in emission** or **trace-envelope native metadata v1**.
