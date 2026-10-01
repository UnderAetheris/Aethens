# Next session: start here

## 1. Get CI green (P0-1)

1. Open GitHub Actions for the latest `main` run, read failing logs for `lint`, `test`, `repository-integrity`.
   - If you lack log access, ask the owner to run locally and paste output:
     ```powershell
     ruff check src/ tests/ scripts/
     python -m pytest tests/ -q -x
     python scripts/check_architecture_integrity.py --check
     ```
2. Fix lint first (mechanical), then integrity findings, then tests. One PR per root cause.
3. Do not weaken any gate or test to get green. If a test is wrong, fix it and explain why in the PR.

## 2. Tidy root (P1-2, P1-3), locally with history

```bash
git mv "Aetheris Architecture v1.0 (living spec)-20260709161540.md" docs/architecture/LIVING_SPEC.md
mkdir -p docs/reports
git mv CHANGESET_IMPLEMENTATION_REPORT.md PHASE0_BLOCKER_FIX_REPORT.md TRACE_REPLAY_IMPLEMENTATION_REPORT.md docs/reports/
```
Update links in `AGENTS.md`, `specs/README.md`, `handoff/HANDOFF_REPORT.md`. Run the integrity check (it does not reference these paths, verified 2026-10-01).

## 3. Start Phase 1 (F01 + F13)

- Read `specs/F13_model_providers_router.md` and existing `src/aetheris/model/`.
- Design note PR first, then `ModelRouter` with injectable transports, budgets, cache, redaction, `Abstain`.
- Register nothing new in authority unless the router adds a boundary (it should reuse `network_egress.model_provider`).

## 4. In parallel: F26 M1

- `shell/src/styles/tokens.css` from `docs/design/DESIGN_SYSTEM.md`, primitives (Button, Card, Badge, StatusDot, Skeleton, EmptyState, ErrorState, Toast) with Vitest tests. No behavior change.

## 5. End of session

Update `CURRENT_STATE.md`, this file, `CHANGELOG.md`, and add `snapshots/YYYY-MM-DD_session-N.md`.
