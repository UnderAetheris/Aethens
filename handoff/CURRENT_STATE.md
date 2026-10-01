# Current state

_As of 2026-10-01._

## Built (backend, Phase 0)

Per the README capability table and living spec: config, tools, safety, controller, planner, executive, memory (event/knowledge/experience), evaluation, skills, skill promotion (off), plan review, reflection, autonomous loop (**partial**), self repair, model providers (off), model patch (off), understanding (off), reasoning (on), experience recording (on) / consumption (hold, off), hierarchy (off), research (on), research reliability (on), API bridge (off), unattended supervisor (off), unattended outcome learning (hold, off), frontend shell (unmeasured), trace replay. Plus changeset rollback receipts and recovery drill harness.

Note: "production readiness" is `unknown` for every capability in the ledger. Nothing is production-ready yet.

## Built (UI)

Thin React shell: Composer, QueueList, TaskDetail, Indicators, ActivityLog, ConnectionBanner, Skeletons; API client with tests; polls the bridge every 1s. Not the product UI yet (see F26).

## Docs and process

Specs F00-F26, INVENTORY, AGENTS.md, CONTRIBUTING, SECURITY, CHANGELOG, templates, docs/ (product, design, architecture, engineering), handoff/.

## Not built (specified)

Free-tier model router (F13), task queue v1 completion (F02), durable learned keywords + `revert_last` (F08), permission tiers + approvals inbox (F04), user profile memory (F06), reports/Level (F21), chat endpoint (F22), curiosity (F16), AFK mode (F17), Guardian (F19), vault (F20), self-code evolution (F14), product UI (F26), `coding_tasks_v1` benchmark (F07).

## Known issues (P0 first)

| ID | Issue | Notes |
| --- | --- | --- |
| P0-1 | **CI red on `main`**: lint, test, coverage, repository-integrity, changeset-rollback-contract failing. Gates (reasoning, research, hierarchy, unattended, trace-smoke) pass. | Present before session 2 docs work (docs-only PR #1 showed the same failures; markdown cannot affect ruff). Diagnose from Actions logs or local run. Likely candidates: ruff violations in `tests/`/`scripts/` (Phase 0 report only linted changed files), integrity findings that also fail `tests/test_architecture_integrity.py` (which would explain test + coverage + changeset job together). |
| P1-1 | `test_output.txt` was tracked as a symlink | Removed in session 2 |
| P1-2 | Living spec has a timestamped filename with spaces at repo root | Rename with `git mv` locally to keep history: `docs/architecture/LIVING_SPEC.md`, then update links in AGENTS.md, specs/README.md, handoff. |
| P1-3 | `*_REPORT.md` milestone reports at root | Move with `git mv` to `docs/reports/` |
| P1-4 | UI tests not in CI | Blocked on lockfile policy (Q8) |
| P2-1 | ClickUp doc "Self-Improving AI Assistant: Master Spec" still exists | Owner deletes manually; GitHub is the source of truth |

## Verification status of this session

The session had GitHub read/write but **no ability to run pytest/ruff** and no CI log access. All session-2 changes are docs plus deletion of untracked-by-intent artifacts; none touch `src/`, `tests/`, `scripts/`, ledgers, or CI.
