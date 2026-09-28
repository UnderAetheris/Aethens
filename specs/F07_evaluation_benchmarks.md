# F07: Evaluation Engine & benchmark suites

**Status:** `built`
**Default:** on
**Module:** `src/aetheris/evaluation/`

## 1. Purpose
The arbiter of every change. Nothing is "better" without a number.

## 2. Current state
Hermetic Controller per case, recording shim for tool choice, exact-output checks, `eval_case` + `eval_summary` events. Specialized gates: reasoning, hierarchy, research (narrow/wide/hardening), reliability (eval + coverage canary), unattended. All in CI.

## 3. Suites to add
| Suite | Measures | For |
| --- | --- | --- |
| `coding_tasks_v1` (30-50 tasks, hidden tests) | pass rate, repairs, tokens | F10, F14 |
| `retrieval_v1` | precision@5 | F06 |
| `curiosity_v1` | weakness detection precision | F16 |
| `afk_session_v1` | proposal usefulness, unsafe requests (must be 0) | F17 |
| `guardian_v1` (fixture event logs) | detection precision/recall, false alarm rate | F19 |
| `persona_v1` | injection resistance, refusal correctness | F00 |

## 4. Rules
- Benchmarks and gates are T3 protected (F04)
- Held-out split never visible to Learning/curiosity
- Scores stored per git SHA as evidence records
- New suite = frozen fixtures + divergence precondition + control cases

## 5. Risks
Goodhart (overfitting to the suite) -> held-out split, periodic fixture rotation by the owner, reasoning `hidden_overfit` check.

## 6. Tests
`test_heldout_not_readable_by_learning`, `test_scores_keyed_by_sha`.
