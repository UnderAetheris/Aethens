# F11: Deliberative reasoning

**Status:** `built`, default-on (5-clause gate PASS, CI guard)
**Module:** `src/aetheris/reasoning/`

## 1. Purpose
Read-only advisor that surfaces facts the Planner, Reflection, and Learning already consume, and abstains on thin evidence.

## 2. Current state
`Deliberation` immutable, schema cannot express an action. Seams: planner `skill_vs_decompose`, reflection `safer_repair`, learning `overfit_adoption`. Abstention precision/recall 1.0. Opt-out `AETHERIS_REASONING=off`.

## 3. Next
- Consume research evidence as `Observation`s (already allowed) for curiosity (F16) prioritization
- Model-enriched deliberation (F13) re-gated on the same 5 clauses
- Explanation output feeds F21 ("why did you do that?")

## 4. Rules
No authority, ever. Can only make Learning more conservative.

## 5. Tests to add
`test_deliberation_renders_human_explanation`, `test_model_enrichment_off_is_byte_identical`.
