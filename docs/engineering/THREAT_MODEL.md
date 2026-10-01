# Threat model

## Assets

1. Owner's files and OS integrity
2. Owner's secrets (API keys, tokens, notes)
3. Aetheris's own integrity (safety layer, gates, ledgers)
4. Owner's privacy (logs, profile, browsing signals)

## Threats and mitigations

| # | Threat | Vector | Mitigation |
| --- | --- | --- | --- |
| T1 | Prompt injection | Web page, file, email, tool output says "run X" | Content is data; research schema cannot express actions; injection fixtures in CI |
| T2 | Self-modification of guards | Learning/patching edits safety, gates, tests | T3 hard locks on protected paths; AST tripwire; human-only commits for ledgers/CI |
| T3 | Reward hacking | Agent weakens benchmark to "improve" | Benchmarks protected, held-out split, zero-regression rule, reasoning overfit check |
| T4 | Data exfiltration | Model provider or research egress leaks files/secrets | Redaction before send, allowlist + GET-only perimeter, vault, no auth/cookies |
| T5 | Destructive command | Shell/tool misuse | Safe mode, shell allowlist, path scoping, tiers, approvals, undo hooks |
| T6 | Approval fatigue | Owner rubber-stamps | Clear previews, batching limits, daily cap, risk tier badge |
| T7 | Forged approval | Agent creates its own approval token | `approve_own_proposals = none`; tokens bound to action hash; created only via owner-authenticated API |
| T8 | Local network attack on API | Another device calls the bridge | Bind 127.0.0.1, local auth token for shell |
| T9 | Supply chain | Malicious dependency | Pinned deps, minimal deps, Dependabot (to enable), secret scanning |
| T10 | Runaway AFK | Infinite browsing / cost | Session budgets, supervisor fail-closed, unsafe-request clause absolute |

## Out of scope

Antivirus-grade malware detection (Windows Defender owns that), network IDS, kernel-level protection.
