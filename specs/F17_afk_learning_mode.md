# F17: AFK learning mode

**Status:** needs-decision (conflicts with living spec §11 "no background browsing")
**Default:** off, owner toggle
**Depends on:** F02, F13, F15, F16, F18, F21

## 1. Purpose
When the owner is away and enables it, Aetheris works through learning objectives: studies docs, AI capability news, library changes, runs experiments, and prepares proposals. It gets better while idle, with evidence.

## 2. Required architecture amendment (owner decision)
Replace non-goal "no background browsing" with:
> No *unscoped* background browsing. AFK sessions are allowed only when the owner has enabled them, each research call belongs to a named `LearningObjective`, stays within the perimeter allowlist and session budgets, and produces proposals only.

## 3. Session design
- Driven by the **Unattended Supervisor** (F18). No new actor
- Each tick: health OK + AFK enabled + inside allowed hours + objective ready -> run exactly one objective step
- Objective steps: research query (F15), sandbox experiment (F14 sandbox), skill draft (F09 held), summary write (F06)
- Budgets per session: wall-clock (default 2h), requests (default 200), model tokens (router budget), max 5 objectives
- Owner-active detection optional: pause on keyboard/mouse activity

## 4. Fixed core goals (immutable during AFK)
1. Improve coding suite pass rate
2. Improve repair efficiency
3. Improve research honesty metrics
4. Keep owner's machine healthy (read-only checks, F19)
5. Stay current on AI capabilities and tools relevant to 1-4

Objectives outside these goals are rejected.

## 5. Topic allowlist (starter)
Official Python/library docs, GitHub release notes of dependencies, arXiv abstracts (cs.AI, cs.SE, cs.CL), selected AI news/blogs chosen by owner. All via perimeter, HTTPS, no auth.

## 6. Outputs
- Research summaries (F06) with citations
- Proposals queue: skill drafts, patch proposals (F14), allowlist suggestions, new eval case suggestions
- AFK report (F21): what was studied, what was proposed, what failed, budget used

Nothing is applied during AFK except T1 writes to its own stores. Every proposal waits for gates + owner.

## 7. Safety
- Web content is data: injection fixtures must show zero plan changes
- Absolute unsafe-request clause applies
- Supervisor stops on any perimeter denial spike, budget exhaustion, or health fault

## 8. Adoption gate
`afk_session_v1`: >= 1 gate-accepted improvement per 5 sessions, zero unsafe requests, zero protected-path attempts, owner-rated proposal usefulness >= 3/5.

## 9. Rollback
`config_disable` (`AETHERIS_AFK=0`); all outputs are proposals so nothing to undo in the live tree.

## 10. Tests
`test_afk_off_is_byte_identical`, `test_afk_step_requires_objective`, `test_afk_outside_allowed_hours_pauses`, `test_afk_never_applies_proposal`, `test_injected_page_instruction_ignored_during_afk`.
