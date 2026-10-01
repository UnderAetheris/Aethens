# Quality bar

The standard is "built by a senior product team", not "it runs on my machine".

## Definition of done

A change is done only when all are true:

1. **Spec**: `specs/FXX` exists, status updated, open questions resolved or logged.
2. **Correct**: unit tests for happy, failure, and edge paths. Adversarial tests for any safety-relevant surface.
3. **Gated**: feature gate exists (if behavior changes), evidence record written before default flips.
4. **Safe**: no new execution/egress path; ledgers updated; protected paths untouched by automation.
5. **Green**: `ruff`, `pytest`, integrity check, all specialized gates, UI `npm test` + `npm run build`.
6. **Reversible**: rollback kind declared and tested.
7. **Observable**: events logged with typed fields; unknown stays unknown.
8. **Documented**: spec, CHANGELOG, `handoff/CURRENT_STATE.md`.
9. **UX** (if UI): five states, keyboard path, design tokens, reduced motion, 1280x800 check.

## Quality pass checklist (run before every merge)

### Code
- [ ] Names say what things are; no dead code; no commented-out blocks
- [ ] No bare `except`, no silent fallbacks, no magic numbers without a named constant
- [ ] Pure functions where possible; side effects only at registered boundaries
- [ ] Types complete; frozen dataclasses for records
- [ ] Functions under ~50 lines; modules single-purpose

### Tests
- [ ] Deterministic (no wall clock, no live network, no random without seed)
- [ ] Off-path byte-identical test for every new flag
- [ ] At least one test that tries to break the safety rule the feature relies on

### Security
- [ ] No secrets in code, logs, fixtures, prompts
- [ ] External content treated as data
- [ ] Inputs validated at API boundary

### Performance (owner laptop: i5-8365U, 8 GB)
- [ ] Idle RSS < 1.5 GB, eval run < 3 GB
- [ ] API p95 < 200ms for status endpoints
- [ ] UI interaction feedback < 100ms

### Repo hygiene
- [ ] No generated/build/editor artifacts tracked
- [ ] No stray files at repo root

## Quality debt register

Known gaps live in `handoff/CURRENT_STATE.md` under "Known issues". Never hide debt; log it.
