# F12: Repository understanding

**Status:** `built`, default-off
**Module:** `src/aetheris/understanding/`

## 1. Purpose
AST-derived model of the codebase (symbols, exports, dependents) so repairs and patches are grounded in facts.

## 2. Current state
`RepoUnderstanding` query surface (`defines`, `exporting_module`, `find_helper`), scan journal, backup restore.

## 3. Next
- Index its own repo (Aetheris) so F14 can reason about self-patches
- Mark protected paths in the model so planners see them as immovable
- Default-on gate: repair first-attempt success up, zero regressions

## 4. Rules
Research may annotate beside the model, never rewrite AST truth.

## 5. Tests to add
`test_protected_paths_flagged_in_model`, `test_self_index_matches_git_tree`.
