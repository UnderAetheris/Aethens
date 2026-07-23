# Aetheris ChangeSet & Rollback Receipt Contract v0

**Document type:** Corrective implementation specification for the coding agent
**Milestone class:** Mutation accountability, rollback evidence, and read-only audit linkage
**Implementation posture:** Minimal-first, additive-only, fail-closed
**Authority change:** None permitted
**Verified repository revision:** `31704237fd52ae7738ffd8d5f615f6fd48880713`

---

## 0. Executive decision

The project is moving in the right direction, but this milestone is **not greenfield**. The checked repository already contains:

```text
src/aetheris/changeset/__init__.py
src/aetheris/changeset/model.py
src/aetheris/changeset/canonical.py
src/aetheris/changeset/view.py
tests/test_changeset.py
```

The trace layer also already imports ChangeSet types and contains ChangeSet/Rollback reducers. Therefore, the coding agent must treat v0 as an **audit, correction, separation, and completion** milestone—not as permission to add a second implementation.

The existing code is a useful prototype, but it does not yet prove the requested contract. In particular:

- models accept arbitrary IDs instead of validating derived IDs;
- mandatory hash strings cannot represent unknown identity safely;
- inverse operations are free-form strings and could be mistaken for executable instructions;
- rollback restoration is not cryptographically linked to the original before-state;
- multi-step rollback evidence has no ordering/group contract;
- trace imports changeset code, coupling the earlier trace milestone to the later milestone;
- existing tests mostly prove object construction, rendering, and deterministic helper output, not restoration truthfulness;
- the current trace replay implementation itself has correctness gaps that must be closed before ChangeSet integration can be trusted.

The minimal safe design is:

> ChangeSet and RollbackReceipt remain immutable data contracts projected from already persisted evidence or constructed by pure factories. They do not perform changes or rollbacks, own no writer, and add no runtime hook in v0.

---

## 1. Non-goals

Do not:
- execute rollback tokens during replay or inspection;
- add a new write control plane;
- modify existing writer code, journal formats, or snapshot schemas;
- add a distributed service, database, queue, or background worker for change tracking;
- widen authority for any existing capability;
- modify SafetyLayer, NetworkPerimeter, planner, reflection, learning, reasoning, experience, research, unattended, or trace/replay internals;
- replace existing append-only stores.

---

## 2. Core design decision: accountability records, not control plane

Existing subsystems already own their append-only persistence. This milestone defines the canonical shape of change-set and rollback-receipt records that subsystems may optionally append through their existing channels.

No new runtime authority is introduced because:
- Change sets are data, not execution;
- Rollback receipts are audit evidence, not execution;
- Neither record type is required for ordinary runtime behavior;
- Neither record type grants new permissions to any subsystem.

---

## 3. Architectural invariants

### C-01 — Additive-only records

ChangeSet and RollbackReceipt records may be appended to existing append-only stores. They must never modify, truncate, or rewrite existing records.

### C-02 — Append-only history

Once written, a change set or rollback receipt is immutable. Corrections are new records, not edits.

### C-03 — No authority widening

The change set capability carries zero authority. No subsystem gains new permissions by emitting or receiving change-set records.

### C-04 — No rollback execution

Rollback receipts are inert audit text. Replay never invokes, simulates, or executes a recorded rollback token.

### C-05 — Hash linkage

Every change set contains `before_hash` and `after_hash` computed from the exact pre-mutation and post-mutation byte representation. Rollback receipts contain `before_hash` and `after_hash` of the change-set record they reference.

### C-06 — Inverse operation reference

Every change set contains an `inverse_operation` string that names the declared reverse action. The string is descriptive; it is not executed.

### C-07 — Trace linkage

Change sets may reference a `trace_id`, `task_id`, `session_id`, and `plan_id`. Rollback receipts reference a `change_id`. The linkage is one-way and declarative.

### C-08 — Unknown propagation

Missing required fields become typed `TraceUnknown` entries. They are never filled with empty strings, zeros, current state, or guessed identifiers.

### C-09 — Read-only inspection

Change-set and rollback-receipt views can select, filter, render, and validate. They cannot append, edit, delete, execute, or mutate history.

### C-10 — No new runtime dependency

The change-set package depends only on the standard library and the existing `aetheris.trace` package. Existing subsystems depend on change-set code only if they explicitly import it.

---

## 4. ChangeSet model

File: `src/aetheris/changeset/model.py`

```python
@dataclass(frozen=True)
class ChangeSet:
    schema_version: int
    change_id: str
    trace_id: TraceValue
    task_id: TraceValue
    session_id: TraceValue
    plan_id: TraceValue
    capability_id: str
    owner_subsystem: str
    change_kind: ChangeKind
    disposition: MutationDisposition
    authority_class: str
    target: ObjectIdentity
    before: ObjectIdentity
    after: ObjectIdentity
    inverse: InverseReference
    rollback_ref: TraceValue
    revision: TraceValue
    config_fingerprint: TraceValue
    policy_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    provenance: Provenance
    unknowns: tuple[TraceUnknown, ...]
    observed_at: TraceValue
```

### 4.1 ChangeKind

Allowed values:
- `file_edit`
- `plan_edit`
- `skill_promotion`
- `skill_retirement`
- `learning_adoption`
- `learning_demotion`
- `session_checkpoint`
- `research_evidence_append`
- `config_toggle`
- `benchmark_adoption`
- `journal_append`
- `snapshot_update`
- `model_patch_proposal`
- `model_patch_validation`
- `experience_append`
- `knowledge_append`
- `unknown`

No broad wildcard category.

### 4.2 MutationDisposition

Allowed values:
- `reversible`
- `compensatable`
- `append_only`
- `rebuildable_snapshot`
- `ephemeral`
- `unknown`

The disposition declares whether the mutation can be undone, compensated, or is append-only.

### 4.3 before / after

These are `ObjectIdentity` carriers that reference:
- a snapshot path or key via `locator`;
- the exact SHA-256 digest of the pre-mutation or post-mutation state;
- the `size_bytes` and `version_ref` of the object state;
- or `unknown` when the exact identity cannot be preserved.

Each `ObjectIdentity` carries `object_type`, `scope`, `locator`, `hash_algorithm`, `digest`, `size_bytes`, and `version_ref`.  
When `hash_algorithm == "sha256"`, the digest must be exactly 64 lowercase hex characters.

### 4.4 target

An `ObjectIdentity` declaring the logical target of the mutation. `target.scope` and `target.object_type` must match `before` and `after` for direct restoration claims.

### 4.5 inverse

An `InverseReference` declaring the named reverse action:

```python
@dataclass(frozen=True)
class InverseReference:
    kind: RollbackKind
    owner_subsystem: str
    authority_boundary: str | None
    target: TraceValue
    preconditions: tuple[str, ...]
    expected_restore_identity: ObjectIdentity | None
    authorization_required: TraceValue
    executable: Literal[False] = False
```

The `executable` field is always `False`. This is a descriptive reference, not an executable instruction.

Allowed `RollbackKind` values:
- `git_revert`
- `restore_snapshot`
- `tombstone_unretire`
- `config_disable`
- `discard_sandbox`
- `resume_checkpoint`
- `not_applicable`
- `unknown`

Append-only mutations must have `inverse.kind` of `not_applicable` or `unknown`.

### 4.6 rollback_ref

A `TraceValue` carrier that may reference a persisted rollback record. It is never interpreted or executed by the change-set package.

### 4.7 policy_fingerprint

A `TraceValue` carrier for the active policy configuration at the time of the mutation.

### 4.8 source_event_ids

Ordered tuple of trace event IDs that contributed evidence for this change set.

### 4.9 observed_at

A `TraceValue` carrier recording when the mutation was observed in the persisted record.

---

## 5. RollbackReceipt model

File: `src/aetheris/changeset/model.py`

```python
@dataclass(frozen=True)
class RollbackReceipt:
    schema_version: int
    receipt_id: str
    change_id: str
    trace_id: TraceValue
    rollback_group_id: TraceValue
    sequence_index: int | None
    parent_receipt_id: TraceValue
    depends_on_receipt_ids: tuple[str, ...]
    rollback_kind: RollbackKind
    rollback_target: ObjectIdentity
    outcome: RollbackOutcome
    observed_pre_rollback: ObjectIdentity
    observed_post_rollback: ObjectIdentity
    confirmation: RestorationConfirmation
    revision: TraceValue
    config_fingerprint: TraceValue
    policy_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    provenance: Provenance
    unknowns: tuple[TraceUnknown, ...]
    attempted_at: TraceValue
    confirmed_at: TraceValue
```

### 5.1 RollbackOutcome

Allowed values:
- `not_attempted`
- `succeeded`
- `failed`
- `partial`
- `blocked`
- `unknown`

### 5.2 RestorationConfirmation

```python
@dataclass(frozen=True)
class RestorationConfirmation:
    status: Literal[
        "confirmed",
        "partially_confirmed",
        "not_confirmed",
        "not_applicable",
        "unknown",
    ]
    expected: ObjectIdentity | None
    observed: ObjectIdentity | None
    verifier: TraceValue
    compared_fields: tuple[str, ...]
    mismatches: tuple[str, ...]
```

A `confirmed` status requires:
- `outcome == RollbackOutcome.SUCCEEDED`
- `expected` and `observed` are both non-None
- both have the same `object_type` and `scope`
- both digests are known and equal
- `verifier.state == "known"`
- no mismatches
- no required unknowns beyond `missing_config` and `missing_policy`

A `partially_confirmed` status indicates a `succeeded` or `partial` outcome with known mismatches or unverified fields.

### 5.3 rollback_group_id

A `TraceValue` carrier identifying the group this receipt belongs to. All receipts in a multi-step rollback share the same group ID.

### 5.4 sequence_index

Zero-based position within the rollback group. `None` for unordered receipts.

### 5.5 parent_receipt_id

For ordered multi-step groups, the preceding receipt. `not_applicable` for the first receipt in a group.

### 5.6 depends_on_receipt_ids

Ordered tuple of receipt IDs this receipt depends on.

### 5.7 observed_pre_rollback / observed_post_rollback

`ObjectIdentity` carriers for the state before and after the rollback attempt:
- `observed_pre_rollback.digest` must match `change_set.after.digest` (when both known)
- `observed_post_rollback.digest` must match `change_set.before.digest` (when both known)

### 5.8 Hash linkage

- `observed_pre_rollback` links to the change-set's `after` state
- `observed_post_rollback` links to the change-set's `before` state
- The `confirmation` struct independently verifies verifier, compared fields, and mismatches
- Together they form a tamper-evident chain grounded in `ObjectIdentity` digests

### 5.9 Append-only and checkpoint semantics

- Rollback receipts for append-only mutations may record outcomes but must not claim `confirmed` when the underlying evidence cannot be restored.
- `resume_checkpoint` is valid only for `rebuildable_snapshot` or `ephemeral` dispositions.
- `discard_sandbox` applies only to `scope == "sandbox"` targets.

---

## 6. Canonicalization and identity

File: `src/aetheris/changeset/canonical.py`

- `canonical_json`: same as trace package (sort_keys, compact separators, reject NaN/Infinity)
- `canonical_hash`: SHA-256 of canonical JSON (with dataclass auto-conversion)

### 6.1 ChangeSet preimage

```json
{
  "schema_version": 1,
  "trace_id": [state, value],
  "capability_id": "...",
  "owner_subsystem": "...",
  "change_kind": "file_edit",
  "disposition": "reversible",
  "target": { "object_type": "...", "scope": "...", "locator": [state, value], "hash_algorithm": "...", "digest": [state, value], "size_bytes": [state, value], "version_ref": [state, value] },
  "before": { ...same structure... },
  "after": { ...same structure... },
  "revision": [state, value],
  "source_event_ids": ["evt_..."],
  "observed_at": [state, value]
}
```

### 6.2 RollbackReceipt preimage

```json
{
  "schema_version": 1,
  "change_id": "chg_...",
  "rollback_group_id": [state, value],
  "sequence_index": 0,
  "rollback_kind": "git_revert",
  "rollback_target": { "object_type": "...", "scope": "...", "locator": [state, value], "hash_algorithm": "...", "digest": [state, value], "size_bytes": [state, value], "version_ref": [state, value] },
  "observed_pre_rollback": { ...same structure... },
  "observed_post_rollback": { ...same structure... },
  "confirmation": { "status": "...", "expected": { ...identity preimage... }, "observed": { ...identity preimage... }, "verifier": [state, value], "compared_fields": [...], "mismatches": [...] },
  "outcome": "succeeded",
  "revision": [state, value],
  "source_event_ids": ["evt_..."],
  "attempted_at": [state, value]
}
```

### 6.3 Identity derivation

- `change_id`: `chg_` + SHA-256(canonical JSON of ChangeSet preimage)[:32]
- `receipt_id`: `rcpt_` + SHA-256(canonical JSON of RollbackReceipt preimage)[:32]

Deterministic: same fields produce the same ID every time.

---

## 7. Integration points

Change-set and rollback-receipt records are append-only data. Existing subsystems may emit them through their existing stores:

| Integration point | Owner subsystem | Existing store | Suggested record kind |
| --- | --- | --- | --- |
| File edits | controller | MemoryStore JSONL | `change_set` |
| Plan edits | planner | PlanStore sidecar | `change_set` |
| Skill promotion / retirement | skills | MemoryStore JSONL | `change_set` |
| Learning adoption / demotion | learning | MemoryStore JSONL | `change_set` |
| Session checkpoint changes | unattended | SessionJournal JSONL | `change_set` |
| Research evidence records | research | ResearchJournal JSONL | `change_set` |
| Configuration toggles | config | MemoryStore JSONL | `change_set` |
| Benchmark adoption artifacts | evaluation | MemoryStore JSONL | `change_set` |
| Journal / snapshot updates | various | respective stores | `change_set` |
| Rollback execution | various | respective stores | `rollback_receipt` |

No subsystem is required to emit these records. The contract defines the format for those that do.

---

## 8. Trace/replay integration

File: `src/aetheris/changeset/projector.py`

Two projector functions project ChangeSet and RollbackReceipt objects into `TraceEnvelope` objects:
- `change_set_to_envelope` — projects a `ChangeSet` record
- `rollback_receipt_to_envelope` — projects a `RollbackReceipt` record

This allows trace/replay to:
- include change sets in envelope lineage;
- validate hash linkage between change sets and rollback receipts;
- reconstruct change-set summary state via reducers;
- inspect rollback chains through the existing trace view.

The projectors are additive. They do not modify existing adapters or the `TraceEnvelope` schema.

### 8.1 Replay reducers

Four new reducers are registered in `src/aetheris/trace/replay.py`:

| Reducer name | Input | Output |
| --- | --- | --- |
| `change_set_summary` | `event_type == "change_set"` | `state["change_kind_counts"]`, `state["change_capabilities"]` |
| `rollback_summary` | `event_type == "rollback_receipt"` | `state["rollback_kind_counts"]` |

These are invoked alongside the existing reducers in the `ReplayEngine`.

---

## 9. Read-only inspection design

File: `src/aetheris/changeset/view.py`

- `ChangeSetView`: renders a change set as `summary` (text) or `to_dict` (JSON)
- `RollbackReceiptView`: renders a rollback receipt as `summary` (text) or `to_dict` (JSON)

File: `scripts/inspect_trace.py`

Extended to accept:
- `--source change_set=<path>` — load change-set JSONL records
- `--source rollback_receipt=<path>` — load rollback-receipt JSONL records

No write controls in any view.

---

## 10. Rollback taxonomy

| Kind | Description | Safety property |
| --- | --- | --- |
| `git_revert` | Revert to a prior commit | Reversible; does not widen authority |
| `restore_snapshot` | Restore a prior snapshot version | Read-only restore from existing snapshot |
| `tombstone_unretire` | Reverse a tombstone / retirement | Reversible skill/lifecycle action |
| `config_disable` | Disable a config toggle | Reduces capability surface |
| `discard_sandbox` | Discard a sandbox copy | Destroys only disposable copy |
| `resume_checkpoint` | Resume from a checkpoint | Restores known quiescent state |
| `not_applicable` | No rollback defined | Mandatory infrastructure |
| `unknown` | Rollback mechanism unknown | Unknown remains unknown |

### 10.1 Safety rules

- Rollback must never reduce safety just to restore availability.
- Rollback must never widen authority.
- Rollback must not destroy append-only evidence.
- `not_applicable` is used for mandatory infrastructure (e.g., SafetyLayer) that cannot be rolled back.
- `unknown` is used when the rollback mechanism is not declared.

---

## 11. Safety and authority

The change-set package:
- contains no tool, process, network, mutation, config writer, skill promoter, approval, or model provider references;
- is not imported by any runtime subsystem unless explicitly opted in;
- holds zero authority in `architecture/authority.json` (no new capability added);
- does not modify `SafetyLayer`, `NetworkPerimeter`, planner, reflection, learning, reasoning, experience, research, unattended, or trace/replay contracts.

---

## 12. Replay integration

- A rollback receipt references a `change_id`.
- A change set references a `trace_id`.
- When projected through the trace envelope adapters, rollback receipts link to change sets via causal edges (`cause_event_ids`).
- Deterministic replay remains read-only and does not perform rollback.
- Replay can show which change set created which later receipt by following the envelope graph.

---

## 13. Observability

Read-only views expose:
- change-set lineage (before_hash → after_hash → inverse_operation);
- rollback receipt chain (change_id → rollback_kind → confirmed_restored_state);
- capability and subsystem frequency summaries;
- unknowns and missing evidence.

No write controls exist in any view.

---

## 14. Required tests

1. ChangeSet creation and frozen immutability
2. RollbackReceipt creation and frozen immutability
3. Canonical JSON stability across key order
4. Deterministic change_id derivation
5. Deterministic receipt_id derivation
6. Different before_hash produces different change_id
7. ChangeSetView summary and dict rendering
8. RollbackReceiptView summary and dict rendering
9. ChangeSetAdapter projection
10. RollbackReceiptAdapter projection
11. ChangeSet envelope included in replay state reconstruction
12. Trace linkage (change_set → trace_id)
13. Rollback linkage (receipt → change_id)
14. Unknown propagation
15. No authority widening imports in changeset package
16. Byte-identical off-path behavior (existing tests unchanged)
17. No regression to existing canaries and gates

---

## 15. Evaluation strategy

| Metric | Target |
| --- | --- |
| Projection coverage | 100% of supplied change_set / rollback_receipt records project or fail explicitly |
| Payload preservation | 100% for projected records |
| Deterministic IDs | same inputs produce same change_id / receipt_id |
| Authority grant delta | 0 |
| Runtime artifact byte-difference | 0 with changeset package unused |
| Test / gate regressions | 0 |
| Unknown propagation | all missing required fields surface as TraceUnknown |

---

## 16. Adoption gate

Adopt v0 only if:
- all supplied change_set / rollback_receipt records project or fail explicitly;
- payload preservation is 100% for projected records;
- repeated runs produce identical IDs;
- authority grant delta is zero;
- no existing test/gate regression occurs;
- no hidden write/process/network path is introduced;
- unknown remains unknown.

---

## 17. Next-step recommendation

After ChangeSet & Rollback Receipt Contract v0 proves stable, the highest-value next milestone should remain **Aetheris ChangeSet & Rollback Receipt Contract v0 → integration hardening** or the originally planned **Aetheris ChangeSet & Rollback Receipt Contract v0 → trace-envelope native metadata v1**.

Do not combine this milestone with trace/replay or with execution-path changes.
