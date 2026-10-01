# Testing strategy

## Layers

| Layer | Tool | Scope | Runs |
| --- | --- | --- | --- |
| Unit | pytest | single function/class, hermetic | every push |
| Contract | pytest | ledgers, schemas, receipts, trace replay | every push |
| Gate / benchmark | `scripts/run_*_gate.py` | measured adoption clauses | every push (CI jobs) |
| Adversarial safety | pytest | perimeter hardening, safety bypass attempts, injection | every push |
| Integrity | `check_architecture_integrity.py` | authority, defaults, AST tripwire, artifacts | every push |
| UI unit | Vitest + Testing Library | components, hooks, API client | every push (to add to CI) |
| UI e2e | Playwright (planned) | onboarding, approve flow, chat | nightly / pre-release |
| Recovery drill | `scripts/run_recovery_drill.py` | restore from receipts | owner-triggered |

## Rules

1. No live network in any test. Inject transports.
2. No wall-clock dependence. Inject clocks.
3. Fixtures are frozen and content-hashed; held-out eval splits are never visible to learning code.
4. Every flag: on-path test + byte-identical off-path test.
5. Every safety rule: a test that tries to violate it and must fail.
6. A gate that cannot distinguish good from no-op is invalid (divergence precondition).

## Gaps to close

- UI tests are not run in CI yet: add a `shell` job (`npm ci && npm test && npm run build`). Requires committing a lockfile decision (see OPEN_QUESTIONS: `package-lock.json` is currently forbidden by hygiene rules).
- `coding_tasks_v1` benchmark (F07) does not exist yet; it is the most important missing suite.
