# F14: Model-assisted patching & self-code evolution

**Status:** model-assisted patching `built` (default-off); self-code evolution `proposed`
**Default:** off
**Module:** `src/aetheris/model/` (patch), `src/aetheris/changeset/`
**Boundary:** `sandbox_validation.model_patch`

## 1. Purpose
"Write its own code by seeing mistakes", safely. The system proposes code changes to itself, validates them in a throwaway sandbox, and only a gated, receipted, reversible change lands.

## 2. Current state
`ModelAssistedPatcher` applies diffs in a temp dir, runs allowlisted tests, discards sandbox, returns `PatchProposal` to ReflectionEngine. Live tree never touched by the validator. Changeset + rollback receipt contract exists.

## 3. Evolution loop
1. **Trigger:** eval failure cluster, curiosity finding (F16), repeated repair, or owner request
2. **Hypothesis:** weakness + target suite + expected metric change
3. **Patch:** model generates diff limited to allowed paths (L5 `skills/`, then L6 non-protected `src/`)
4. **Sandbox:** apply, run full test suite + all gates + target suite
5. **Compare:** strictly better on target, zero regressions everywhere, architecture-integrity passes
6. **Land:** commit on `agent/<id>` branch + changeset receipt + evidence record, open PR
7. **Owner merges** (T2 approval). v2 may allow auto-merge for L5 only after a long clean record
8. **Watch:** post-merge eval; automatic `git_revert` if any gate regresses

## 4. Hard limits
- Diff size cap (default 200 lines), one concern per patch
- Cannot touch T3 protected paths (F04 list) or add imports of network/process libs
- Cannot add tools, boundaries, or authority; those need a human spec change
- Max 3 evolution PRs open at once

## 5. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| write_files (live tree) | none | |
| write_files (sandbox) | direct | sandbox_validation.model_patch |
| approve_own_proposals | none | |

## 6. Adoption gate
Over 10 proposals: >= 30% accepted by gate, zero post-merge regressions, zero protected-path attempts reaching sandbox.

## 7. Rollback
`discard_sandbox` pre-merge; `git_revert` post-merge.

## 8. Risks
- Test gaming (patch weakens tests) -> tests are protected; diff touching `tests/` requires owner review flag
- Slow drift in code quality -> ruff + coverage must not drop

## 9. Tests
`test_patch_touching_protected_path_rejected`, `test_patch_adding_network_import_rejected`, `test_post_merge_regression_triggers_revert`, `test_diff_size_cap`.
