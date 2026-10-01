## What and why
<!-- One paragraph. Link the spec: specs/FXX_... -->

## Design
<!-- Components touched, data flow, trade-offs. -->

## Safety and authority
- [ ] No new execution path (all tool actions via SafetyLayer)
- [ ] No new egress path
- [ ] Ledgers updated (`capabilities.json` / `authority.json`) or not needed
- [ ] New flags default-off, off-path byte-identical test added
- [ ] Protected paths untouched (safety, perimeter, eval gates, ledgers, CI) or human-authored

## Evidence
<!-- Gate output, before/after metrics. Unknown = unknown. -->

## Tests
- [ ] `ruff check src/ tests/ scripts/`
- [ ] `python -m pytest tests/ -q`
- [ ] `python scripts/check_architecture_integrity.py --check`
- [ ] UI: `npm test && npm run build` (if shell touched)

## UX (if UI touched)
- [ ] Matches `docs/design/DESIGN_SYSTEM.md`
- [ ] Loading, empty, error, success states
- [ ] Keyboard + screen reader friendly, reduced motion respected

## Docs
- [ ] Spec status updated
- [ ] `CHANGELOG.md`
- [ ] `handoff/CURRENT_STATE.md`
