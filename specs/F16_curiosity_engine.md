# F16: Curiosity engine (weakness discovery)

**Status:** proposed
**Default:** off
**Module:** `src/aetheris/curiosity/` (new)
**Depends on:** F06, F07, F11, F15

## 1. Purpose
"Have curiosity" in an engineering sense: find what the system is bad at or doesn't know, and turn it into a concrete learning objective. Curiosity is **advisory**: it produces objectives, never actions.

## 2. Signals
| Signal | Source |
| --- | --- |
| Failing / flaky eval cases | F07 |
| High repair count per task type | F10, event memory |
| Planner `plan_uncertain` clusters | event memory |
| Research `unknowns` and `contradictions` | F15 |
| Low-usefulness memories | F06 |
| Owner feedback (thumbs down, corrections) | F22 |
| New releases of libraries we depend on | F15 (allowlisted changelogs) |

## 3. Output
```
LearningObjective(
  id, weakness, evidence_refs, target_suite, expected_metric,
  method: research|experiment|skill_proposal|patch_proposal,
  budget: {minutes, requests, tokens}, priority, expires_at)
```
Objectives land in an `objectives` queue consumed by the Executive idle hook (F02) or AFK mode (F17).

## 4. Prioritization
score = impact (failing cases affected) x confidence x (1 / cost), boosted by owner-pinned goals. Reasoning (F11) may lower priority, never raise past owner pins.

## 5. Rules
- Every objective must name a measurable target; no "learn everything about X"
- Max open objectives: 10; stale objectives expire
- Cannot create objectives targeting protected paths

## 6. Authority
modify_plans: delegated (objectives queue only). Everything else: none.

## 7. Adoption gate
`curiosity_v1`: objectives chosen by curiosity lead to more accepted improvements per hour than random objective selection, zero unsafe requests.

## 8. Rollback
`config_disable`.

## 9. Tests
`test_objective_requires_target_suite`, `test_curiosity_holds_no_tool`, `test_objectives_expire`.
