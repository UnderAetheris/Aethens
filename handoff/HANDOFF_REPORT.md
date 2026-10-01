# Handoff report

_Last updated: 2026-10-01. Author: AI co-founder (Claude Opus 5.5 via ClickUp Brain, GitHub access to this repo)._

## 1. In one paragraph

Aetheris is the owner's long-term project: a self-improving personal AI assistant and engineering system that runs on a low-end Windows laptop for $0 (beyond the AI coding agent the owner pays for). It plans, acts through a single safety gate, measures itself on frozen benchmarks, and keeps only proven, reversible improvements. A strong Phase 0 foundation already exists in Python (controller, safety, tools, planner, memory, evaluation, learning, reasoning, hierarchy, research with network perimeter, reliability, unattended supervisor, changesets, trace replay, recovery drills, architecture integrity CI). Product-level features (free-model router, approvals, curiosity, AFK learning, Guardian, vault, reports, real UI) are fully specified in `specs/` and not yet built.

## 2. Who you are on this project

The owner asked for a **long-term technical co-founder and lead AI systems architect**. That means: challenge weak ideas, think several steps ahead, prefer practical engineering, produce production-quality work, and never just agree. You have full authority to branch, commit, and merge in this repo without asking. Stop only for decisions listed in section 9.

## 3. The product

- **Promise:** the personal AI that actually gets better at helping you, and proves it.
- **Wedge vs competitors** (Letta, OpenHands, Goose, Lethe): proven self-improvement (gated, receipted), visible safety boundaries, personal assistant + PC care in one app, runs on cheap hardware for free. See `docs/product/`.
- **Feel:** calm, fast, trustworthy, beautiful. Must not look vibecoded. See `docs/design/`.

## 4. Architecture in 60 seconds

- Spine: `plan -> act safely -> measure -> record -> improve`.
- One execution gate (`SafetyLayer.run`), one research egress gate (`NetworkPerimeter.fetch`), one model egress boundary.
- Advisors (reasoning, understanding, research, reliability, curiosity) are read-only and cannot act.
- Learning changes one bounded lever at a time; accept only if strictly better with zero regressions.
- Everything default-off until a gate passes; off-path byte-identical.
- Machine-checked ledgers (`architecture/*.json`) + AST tripwire enforce all of this in CI.
- Diagrams: `docs/architecture/OVERVIEW.md`.

## 5. Hardware and cost reality

Owner laptop: i5-8365U, 8 GB RAM, Intel UHD 620 (no usable GPU), Windows 64-bit, ~313 GB free. Consequences: no local big models, no Docker Desktop, laptop = body, free cloud tiers = brain (Gemini AI Studio, Groq, OpenRouter free) behind a router with fallback. Optional Ollama 1.5B-3B for tiny jobs. Improvement happens in memory, skills, prompts, planner levers, and gated code, never by retraining the model.

## 6. What exists (see CURRENT_STATE.md for detail)

- Backend Phase 0: complete per README capability table (28 capabilities, most `complete/measured`).
- UI: thin React shell (Composer, Queue, TaskDetail, Indicators, ActivityLog, 1s polling).
- Specs F00-F26, docs, AGENTS.md, handoff (this folder).
- **CI on `main` is red** on lint, test, coverage, repository-integrity, changeset contract. This predates the docs work (a docs-only PR could not break lint). Root cause not yet diagnosed because the session lacked CI log access. **First job of the next session.**

## 7. How we work

`AGENTS.md` sections 5-10. Spec first, smallest slice, tests + gates, ledgers, docs, handoff update, squash-merge on green.

## 8. Roadmap (short)

0 Green CI -> 1 F01 + F13 free-model router -> 2 task queue + durable learning -> 3 permission tiers + approvals inbox -> 4 UI design system + layout + live feed -> 5 profile memory + persona -> 6 reports/Level -> 7 curiosity -> 8 AFK learning -> 9 Guardian read-only + vault -> 10 self-code evolution. Full: `ROADMAP.md`.

## 9. Decisions waiting on the owner

See `OPEN_QUESTIONS.md`. Top items: AFK amendment to the "no background browsing" non-goal; Guardian ask-first vs never split; meaning of "locker"; first free providers; name/tone; an ambiguous "song player and following app" phrase; license; lockfile policy.

## 10. Glossary

| Term | Meaning |
| --- | --- |
| Gate | Measured adoption test; all clauses must pass to flip default-on |
| Off-path | Behavior when a feature flag is off; must be byte-identical to before |
| Lever | The single thing Learning is allowed to change in one attempt |
| Tier T0-T3 | Permission levels: read, reversible write, ask-first, never |
| Perimeter | `NetworkPerimeter`, the only research egress gate |
| Evidence record | JSON in `architecture/evidence/` backing a gate verdict |
| Receipt | Changeset rollback receipt proving a change can be undone |
| AFK mode | Owner-enabled idle learning sessions, objective-scoped, proposals only |
| Level | Scorecard derived from frozen benchmark results, never self-declared |
