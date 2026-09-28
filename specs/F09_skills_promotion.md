# F09: Skills, skill seeds, skill promotion

**Status:** `built` (skills, seeds, repo-aware skills, promotion)
**Default:** skills on; `skill_promotion` off
**Module:** `src/aetheris/skills/`

## 1. Purpose
Reusable "tools made of tools". Repeated successful plans become skills the Planner can select.

## 2. Current state
Skill templates with `matches`, seed skills, repo-aware selection, idle promotion mined from recurring zero-repair plans (`PromotionConfig`: min_recurrence 3, stability_max_repairs 0, budget 1/cycle).

## 3. Skill manifest (target)
```yaml
name: add_unit_test
version: 3
purpose: Add a pytest test for a named function
inputs: {module: str, function: str}
outputs: {test_path: str, passed: bool}
steps: [...existing tool calls...]
dependencies: [read_file, edit_file, run_tests]
success_metrics: {pass_rate: ">=0.9", avg_repairs: "<=0.5"}
provenance: {origin: promoted|seed|owner, evidence: <record id>}
history: [{version, sha, gate, date}]
status: active|held|retired
```

## 4. Rules
- Skills route through SafetyLayer unchanged
- Promotion creates `held` skills; flip to `active` only after gate
- Retirement is a tombstone, never deletion
- A skill cannot call a T3 tool; T2 steps inherit approval requirement

## 5. Adoption gate (promotion default-on)
Promoted skills improve completion or repairs on coding suite with zero regressions across 3 consecutive idle cycles.

## 6. Tests
`test_promoted_skill_starts_held`, `test_skill_with_t3_step_rejected`, `test_retired_skill_not_selected`.
