# F21: Reports & explainability

**Status:** proposed
**Default:** on once built (read-only)
**Module:** `src/aetheris/reports/` (new)

## 1. Purpose
The owner always knows what Aetheris did, learned, proposed, and failed at, and can ask "why?" about any decision.

## 2. Reports
| Report | Cadence | Contents |
| --- | --- | --- |
| Daily | end of day | tasks done/failed, approvals pending, lessons learned, skills changed, Guardian summary |
| AFK | end of session | objectives worked, sources read, proposals, budget used, stop reason |
| Weekly scorecard ("level") | weekly | pass rate per suite vs last week, accepted improvements, reverted changes, reliability, memory growth |
| Incident | on stop-for-review | fault, evidence, suggested fix |

Markdown files under `reports/` (gitignored runtime artifact) + `GET /reports/*`.

## 3. Explain
`explain(event_id | task_id)` reconstructs the chain from event memory + deliberations + gate verdicts: plan chosen, alternatives, safety decisions, evidence cited.

## 4. Rules
- Only observed numbers; unknown shown as unknown
- Failures listed before successes
- Read-only: reports never trigger actions

## 5. Tests
`test_report_numbers_match_evidence_records`, `test_explain_reconstructs_from_trace`, `test_report_lists_failures_first`.
