# F23: Changesets, rollback receipts, trace replay, recovery drills

**Status:** `built`
**Module:** `src/aetheris/changeset/`, `src/aetheris/trace/`
**Docs:** `architecture/CHANGESET_ROLLBACK_RECEIPT_CONTRACT.md`, `architecture/TRACE_REPLAY_CONTRACT.md`, `architecture/RECOVERY_DRILL_HARNESS.md`

## 1. Purpose
Every important change is reversible and auditable; every decision can be replayed.

## 2. Current state
Changeset model/projection/receipts/safety/authority tests; trace envelope + adapters + replay; recovery drill + verification + CI contract.

## 3. Next
- Every F08 lever change and F14 patch must emit a changeset receipt
- Guardian T2 actions (F19) reuse the receipt format for undo manifests
- Monthly recovery drill (owner-triggered) restoring from receipts on a scratch copy

## 4. Tests to add
`test_every_learning_accept_has_receipt`, `test_guardian_action_receipt_restores_state`.
