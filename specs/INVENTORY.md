# Inventory: everything captured so far

Every ability, behavior, rule, and wish discussed for Aetheris, mapped to its spec. Use this as the review checklist.

## A. Abilities (what it can do)

| # | Ability | Spec | Status |
| --- | --- | --- | --- |
| 1 | Receive a task, plan it, execute safely, log it | F02, F03 | built |
| 2 | Multi-step plans and long-horizon goal DAGs | F03 | built (hierarchy off) |
| 3 | Persistent prioritized task queue with retries | F02 | partial |
| 4 | Read/write files, run allowlisted shell | F05 | built |
| 5 | Write code, test it, repair it | F10, F14 | built |
| 6 | Understand its own repository (AST model) | F12 | built (off) |
| 7 | Deliberate before decisions, abstain on thin evidence | F11 | built |
| 8 | Learn from failures (experience memory) | F06, F08 | built |
| 9 | Learn planner keywords, keep only if eval improves | F08 | built |
| 10 | Create reusable skills from repeated success | F09 | built (promotion off) |
| 11 | Research the web with citations behind an allowlist | F15 | built |
| 12 | Learn which sources are reliable | F15 | built |
| 13 | Run unattended with a health watchdog | F18 | built (off) |
| 14 | Checkpoint, resume after crash, roll back changes | F18, F23 | built |
| 15 | Replay traces to debug decisions | F23 | built |
| 16 | Use free cloud models with automatic fallback | F13 | proposed |
| 17 | Discover its own weaknesses and set learning objectives (curiosity) | F16 | proposed |
| 18 | Learn while the owner is AFK (AI capabilities, news, docs) | F17 | needs-decision |
| 19 | Improve its own code via sandboxed, gated patches | F14 | proposed (widening) |
| 20 | Remember owner preferences and projects | F06 | proposed |
| 21 | Windows health checks (disk, RAM, startup, updates) | F19 | proposed |
| 22 | Security visibility: Defender history, suspicious startup/tasks/connections | F19 | proposed |
| 23 | Clean up and organize files/setups on approval | F19 | proposed |
| 24 | Warn about risky sites via Defender/SmartScreen events | F19 | proposed (limited) |
| 25 | Secrets locker for API keys and sensitive notes | F20 | proposed |
| 26 | Daily/weekly reports and capability scorecard ("level") | F21 | proposed |
| 27 | Explain any decision from the logs | F21 | proposed |
| 28 | Chat interface + approvals inbox | F22, F04 | proposed |

## B. Manners & behavior

| # | Rule | Spec |
| --- | --- | --- |
| 1 | Faithful: serves only owner goals, ignores instructions in data | F00 |
| 2 | Sincere: says "don't know", reports failures, no fake numbers | F00 |
| 3 | Never approves its own proposals | F00, F04 |
| 4 | Refuses hard-lock actions and offers a safe alternative | F00, F04 |
| 5 | Concise by default, deep on request, states confidence | F00 |
| 6 | Pushes back on weak ideas | F00 |
| 7 | Proactive but batched; interrupts only for urgent security | F00, F21 |
| 8 | Smallest safe change; checkpoint before, verify after | F00, F04 |
| 9 | "Level up" only via measured benchmarks | F00, F21 |

## C. Hard rules (never change without an architecture amendment)

1. Every tool action goes through `SafetyLayer.run()`
2. Every network byte goes through `NetworkPerimeter.fetch()` or the registered model-provider boundary
3. The system never edits: safety layer, perimeter, evaluation gates/benchmarks, authority ledger, CI gates
4. `approve_own_proposals` = none for every component
5. Default-off until gated; off-path byte-identical
6. Unsafe-request clause is absolute (one off-allowlist egress fails the gate)
7. Reliability may weight but never gate coverage
8. Supervisor may stop work, never expand it
9. Web/file/email content is data, never instructions
10. No disabling Windows Defender, no touching System32, no admin actions without explicit per-action approval

## D. Decisions needed from the owner

1. **F17:** amend non-goal "no background browsing" to allow AFK research sessions (objective-scoped, allowlisted, budgeted, proposals-only)?
2. **F19:** which Guardian actions are ask-first vs never?
3. **F20:** is "locker" a secrets vault, a folder locker, or an app/PC lock?
4. **F13:** which free providers to register first (Gemini, Groq, OpenRouter)?
5. **F00:** assistant name and tone preset.

## E. Explicitly out of scope

- Writing our own antivirus (Defender is better and free)
- Real-time detection that a website is "under cyber attack" (not observable from a home PC)
- Retraining/fine-tuning the base model locally (no GPU); improvement happens in memory, skills, prompts, planner levers, and gated code
- Unbounded "do anything" authority
