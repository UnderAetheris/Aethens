# UX principles

1. **One glance, one decision.** Home answers "does anything need me?" in under 2 seconds.
2. **Show the work, hide the noise.** Live activity is always available, summarized by default, expandable to full trace.
3. **Every action has an undo or a reason it can't.** Toasts carry Undo. Irreversible actions say so before you click.
4. **Approval in one tap, understanding in one click.** Approval cards show what, why, risk tier, preview, undo plan. Keyboard: A approve, D deny, J/K next/prev.
5. **Never block the user.** Background work never freezes UI; long tasks show progress and can be paused.
6. **Keyboard first, mouse friendly.** Ctrl/Cmd+K reaches everything.
7. **Proof over promises.** Any claim of improvement links to its evidence.
8. **Calm notifications.** Interrupt only for security threats or blocked work. Everything else batches into Home and reports.
9. **Five states for every view:** loading, empty (with a next step), partial, error (with recovery), success.
10. **Fast feels trustworthy.** Interactions < 100ms feedback, page < 1s, optimistic UI where reversible.
11. **Accessible by default.** WCAG AA, screen-reader labels, focus order, reduced motion.
12. **First run in under 10 minutes**: install, add a free API key (guided), run a first task, see the first lesson saved.

## UX checklist (per PR touching UI)

- [ ] All five states designed and implemented
- [ ] Keyboard path works end to end
- [ ] Copy follows the voice rules
- [ ] Tokens only, no raw colors
- [ ] Motion has a reduced-motion fallback
- [ ] Tested at 1280x800 (owner's laptop) and 1920x1080
