# Aetheris Unified Trace Envelope & Deterministic Replay Contract v0

**Document type:** Implementation contract and persisted-format inventory
**Milestone class:** Identity, causality, provenance, and read-only reconstruction
**Verification note:** Phase 0 trace corrections applied at revision `31704237fd52ae7738ffd8d5f615f6fd48880713` corrected: adapter malformed-record handling, MemoryStore task_id extraction, source_hash exact-byte semantics, parent/cause validation, actual hash verification, level 4 policy, reducer routing, unknown propagation, canonical fingerprinting, and trace/changeset decoupling.

---

## 1. Purpose

This document defines the canonical trace envelope schema, adapter contract, replay levels, and persisted-format inventory for Aetheris Trace/Replay v0.

---

## 2. Envelope schema

See `src/aetheris/trace/model.py` for the frozen dataclass definitions.

Key types:
- `TraceEnvelope` — canonical event envelope
- `TraceValue` — typed value carrier (known / unknown / not_applicable / redacted / mismatch)
- `TraceUnknown` — missing required fact
- `SourceLocator` — logical source reference
- `Provenance` — derivation metadata
- `EvidenceRef` — evidence catalog reference
- `ReplayContext` — replay input snapshot
- `ReplayFailure` — failure taxonomy entry
- `ReplayResult` — replay output

---

## 3. Canonicalization and identity

See `src/aetheris/trace/canonical.py`.

Canonical JSON uses `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`.

Two hashes:
- `source_hash`: SHA-256 of exact source record bytes (or unknown)
- `payload_hash`: SHA-256 of canonical JSON for the preserved subsystem payload

Event ID derivation: `evt_` + SHA-256(preimage)[:32] where preimage is `schema_version|adapter_id|adapter_version|stream_id|line_or_key|identity_basis`

Trace ID resolution order:
1. persisted `trace_id` from future compatible record
2. `session_id`
3. `goal_id`
4. `task_id`
5. `plan_id`
6. deterministic root from context mapping
7. unknown

---

## 4. Adapter inventory

| Adapter | Store kind | Source format | Subsystem | Capability | Event type |
| --- | --- | --- | --- | --- | --- |
| MemoryStoreAdapter | memory_store | JSONL `{ts, kind, data}` | memory | memory | kind |
| JsonlStoreAdapter | jsonl_store | flat JSONL records | memory/various | memory/various | kind |
| PlanStoreAdapter | plan_store | MultiStepPlan.to_dict() | planner | planner | plan_snapshot |
| ResearchJournalAdapter | research_journal | JSONL `{kind, timestamp, ...}` | research | research | kind |
| HierarchyAdapter | hierarchy_journal | JSONL `{goal_id, timestamp, ...}` | hierarchy | hierarchy | goal_transition |
| UnattendedAdapter | unattended_journal | JSONL `{kind, session_id, data}` | unattended | unattended_supervisor | kind |
| UnderstandingAdapter | understanding_journal | ScanReport JSONL | understanding | understanding | scan_report |
| ReliabilityAdapter | reliability_journal | JSONL `{kind, source_key, ...}` | research | research_reliability | kind |
| EvidenceAdapter | evidence_record | evidence JSON | architecture | varies | adoption_evidence |
| SkillLearningAdapter | skill_learning | flat JSONL records | skills | skills | kind |
| ModelPatchAdapter | model_patch | proposal/validation JSON | learning | model_patch | kind |

---

## 5. Causality rules

- `parent_event_id`: structural containment/sequence parent
- `cause_event_ids`: one or more events whose persisted outcome caused the event
- Not interchangeable

Deterministic inference rules (declared, never timestamp-proximity):
- MemoryStore: none inferred; structural only via explicit `task_id` extraction when present
- Hierarchy: `subgoal_id` → `step_id`; `goal_id` → `goal_id`
- Unattended: `session_id` → `session_id`
- PlanStore: `task_id` → `task_id`; snapshot version ordering

Ambiguity behavior: set `ambiguous_order` or `missing_parent` and fail relevant replay level.
Missing-key behavior: emit typed `TraceUnknown`.

---

## 6. Replay levels

| Level | Name | Question |
| --- | --- | --- |
| 1 | Projection | Can source records be converted into valid envelopes with preserved payload hashes? |
| 2 | Structural replay | Can lineage, per-stream ordering, hashes, revision/config/policy context, and trace membership be validated? |
| 3 | State replay | Can registered pure reducers reconstruct the final logical state? |
| 4 | Decision verification | Can a recorded deterministic decision be recomputed from exact persisted inputs? |

Level 4 is optional per event type. Unsupported replay classes remain `unsupported`.

---

## 7. Reducers

| Reducer name | Subsystem | Input | Output |
| --- | --- | --- | --- |
| task_outcome | memory | MemoryStore events | `state["tasks"][task_id]` |
| plan_state | planner | PlanStore snapshots + step events | `state["plans"][plan_id]` |
| hierarchy_state | hierarchy | GoalJournal transitions | `state["goals"][goal_id].subgoals[step_id]` |
| unattended_state | unattended | SessionJournal events | `state["sessions"][session_id]` |
| research_summary | research | ResearchJournal events | `state["research_kind_counts"]` |
| adoption_summary | architecture | Evidence events | `state["adoption"][capability_id]` |
| change_set_summary | changeset | ChangeSet envelopes | `state["change_kind_counts"]`, `state["change_capabilities"]` |
| rollback_summary | changeset | RollbackReceipt envelopes | `state["rollback_kind_counts"]` |

---

## 8. Authority profile

The trace core has zero authority. The developer CLI has bounded read access only:
- read_files: none
- write_files: none
- execute_commands: none
- reach_network: none
- modify_plans: none
- modify_memory: none
- create_skills: none
- promote_skills: none
- change_config: none
- approve_own_proposals: none

---

## 9. Behavioral neutrality guarantees

- Normal runtime does not import `aetheris.trace`
- Trace code contains no tool, process, network, mutation, config, skill, or approval authority
- Replay never invokes a recorded tool/command/URL/model/callback/repair/promotion/rollback/resume method
- Trace view cannot write, delete, append, resume, rollback, or mutate history

---

## 10. Known limitations

- Read-time projection only
- No whole-program causality proof
- Decision verification requires complete persisted inputs
- Unsupported model-decision replay is `unsupported`, not guessed
- Cross-stream total order is a stable display tie-break, not proof of historical wall-clock order
