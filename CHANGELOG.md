# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: SemVer once 1.0 ships.

## [Unreleased]

### Added
- `specs/`: per-feature specs F00-F26, template, and full inventory of abilities, manners, hard rules, and open decisions.
- `AGENTS.md`: operating manual for AI coding agents.
- `handoff/`: session continuity package (handoff report, conversation log, decisions, current state, roadmap, open questions, mindset).
- `docs/`: product brief and competitive landscape, design system, screens, UX principles, quality bar, testing strategy, threat model, Windows dev setup, architecture overview.
- `CONTRIBUTING.md`, `SECURITY.md`, PR and issue templates, `.editorconfig`.

### Removed
- Tracked build/editor artifacts: `.idea/`, `shell/*.tsbuildinfo`, `shell/vite.config.js`, `shell/vite.config.d.ts` (compiled duplicates of `vite.config.ts`).
- Stray outputs and one-off scripts at repo root: `test_output.txt`, `test_output3.txt`, `fix_phase0_blockers.py` (its fixes are already applied; recoverable from git history).

## Phase 0 history (pre-changelog)

Foundation milestones, see the living spec and `*_REPORT.md` files: controller, safety layer, tools, planner, evaluation, memory, learning v0, reasoning (default-on), hierarchy (default-off), research engine + perimeter (default-on), reliability learning, unattended supervisor (default-off), correctness hardening, architecture integrity baseline, trace replay, changeset rollback receipts, recovery drill harness.
