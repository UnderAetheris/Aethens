# F04: Safety Layer, permission tiers, approvals inbox

**Status:** SafetyLayer `built`; tiers + approvals inbox `proposed`
**Default:** on
**Module:** `src/aetheris/safety/`

## 1. Purpose
The single execution choke point. Extend it with explicit permission tiers and a human approval flow so new powers (Guardian, self-code evolution, cleanup) can exist without becoming dangerous.

## 2. Current state
Ordered deny-wins rules: `safe_mode` gate, `path_within_root`, `shell_allowlist`; dry-run; `undo` hooks (`write_file` -> `.aetheris.bak`); every attempt logged.

## 3. Design: permission tiers

Every tool declares a tier. A new rule `tier_gate` enforces it.

| Tier | Behavior | Examples |
| --- | --- | --- |
| `T0 read` | auto-allowed within scope | read file, list dir, read Defender history, health sample |
| `T1 reversible write` | auto-allowed inside workspace, with undo | edit workspace file, write report |
| `T2 ask-first` | blocked until an owner approval token exists for this exact action | delete/move outside workspace, install package, cleanup, apply skill/code upgrade, run non-allowlisted command |
| `T3 never` | always denied, no approval can unlock | disable Defender/firewall, touch `C:\Windows\System32`, modify registry run keys, edit safety/perimeter/eval/authority/CI files, raise budgets, approve own proposals |

## 4. Design: approvals inbox
- `ApprovalRequest(id, action_request, tier, reason, evidence_refs, diff_preview, undo_plan, expires_at)`
- Stored append-only (`persistence.approvals`, new boundary)
- Owner approves/denies via API (F22). Approval token is bound to the exact action hash; any change invalidates it
- Expiry default 24h; expired = denied
- Batch approval allowed only for identical low-risk T2 actions, max 10

## 5. Protected paths (T3, hard-locked)
`src/aetheris/safety/**`, `src/aetheris/research/perimeter*`, `src/aetheris/evaluation/**` gates, benchmark fixtures, `architecture/authority.json`, `architecture/capabilities.json`, `.github/workflows/**`, `scripts/check_architecture_integrity.py`. Only a human commit changes these.

## 6. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| approve_own_proposals | none (all components, forever) | |
| change_config | none for the system | config.change (human only) |

## 7. Adoption gate
Adversarial suite: every T3 action denied with and without approval; forged/stale/modified tokens rejected; zero regressions in existing safety tests.

## 8. Rollback
`git_revert`; tiers are additive rules, removing the rule restores prior behavior.

## 9. Risks
- Approval fatigue -> owner rubber-stamps. Mitigation: clear diff + undo plan, batching limits, daily cap on T2 prompts.
- Protected path list drifts -> CI test asserts list matches authority ledger.

## 10. Tests
`test_t3_denied_even_with_approval`, `test_approval_token_bound_to_action_hash`, `test_expired_approval_denied`, `test_protected_paths_match_ledger`, `test_agent_cannot_create_approval_for_itself`.
