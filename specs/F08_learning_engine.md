# F08: Learning Engine (lever widening)

**Status:** `built` (keyword lever); persistence + `revert_last()` in progress per living spec "build next"
**Default:** on
**Module:** `src/aetheris/learning/`

## 1. Purpose
Turn failures into one bounded, reversible, measured change at a time.

## 2. Current state
One lever: `Planner.extra_keywords`. Accept only if `new_rate > baseline` and zero regressions. `LearnedKeywordStore` exists; outcome learning and skill promotion paths exist.

## 3. Lever ladder (widen one rung at a time, each gated)

| Rung | Lever | Rollback |
| --- | --- | --- |
| L1 | planner keywords (built) | pop keyword |
| L2 | skill promotion (F09) | tombstone skill |
| L3 | prompt templates for model calls (versioned files) | restore previous version |
| L4 | tool parameter defaults (timeouts, retries) within clamps | config revert |
| L5 | new skill code in `skills/` via sandbox (F14) | git_revert agent branch |
| L6 | non-protected source patches (F14) | git_revert |

Never: safety, perimeter, eval, authority, CI (T3).

## 4. Rules
- One change per attempt, one lever per attempt
- Each accepted change -> KnowledgeEntry + evidence record + changeset receipt (F23)
- `revert_last()` and `revert(id)` available for every rung
- Rate limit: max N accepted changes per day (default 3) so the owner can review

## 5. Adoption gate per rung
Strict improvement on target suite, zero regressions across *all* suites, reasoning did not flag overfit/safety creep.

## 6. Tests
`test_keywords_persist_across_restart`, `test_revert_last_restores_prior_rate`, `test_daily_change_cap`, `test_learning_cannot_touch_protected_paths`.
