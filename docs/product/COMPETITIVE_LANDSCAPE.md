# Competitive landscape (researched 2026-10-01)

Facts below come from public project pages at research time; re-verify before quoting externally.

| Product | What it is | Strength | Weakness we exploit |
| --- | --- | --- | --- |
| **Letta Code** (ex-MemGPT) | Stateful agent harness, memory blocks, skills, "dreaming", git-tracked memory | Most mature memory + self-rewrite story, desktop app | Self-rewrites memory/prompts/harness without a measured accept/reject gate; improvement is asserted, not proven |
| **OpenHands** | Open autonomous coding agent, planning mode, sandbox, MCP | Strong coding benchmark results, big community | No native long-term memory; needs Docker + strong hardware for local; coding-only |
| **Goose** (Block / Linux Foundation AAIF) | General agent, desktop + CLI, 70+ MCP extensions, recipes | Extensibility, prompt-injection detection, Windows support | Not self-improving; no benchmark-proven learning loop |
| **Lethe** | Long-running personal assistant, brain-inspired actors, can propose changes to its own source | Persistent always-on assistant | Self-modification without public gate/ledger discipline; container-heavy |
| **Claude Code / Codex / Copilot CLI** | Vendor coding agents | Best raw models | Paid, cloud-tied, forget across sessions, not personal-assistant scoped |
| **Aider, Cline, Continue** | Pair-programming tools | Fast surgical edits | Single session, no learning |

## Our wedge

1. **Proven self-improvement**: the only one where every learned change passes a frozen-benchmark gate with zero regressions and has a rollback receipt. Make this visible as the Level/scorecard.
2. **Safety you can see**: single execution gate + single egress gate + approvals inbox + hard locks, enforced by CI ledgers. Competitors have permissions; we have *provable* boundaries.
3. **Personal + PC care**: coding assistant, research assistant, and Guardian in one calm app.
4. **Runs on a cheap laptop for $0**: free-tier model router, no Docker, no GPU.

## What to borrow (with our gates)

- MCP compatibility for tools (Goose, OpenHands): adopt as a tool source behind SafetyLayer, never as a bypass
- Memory tiers episodic / semantic / structured (common 2026 pattern): maps to our Experience / Knowledge / Event stores
- Resumable GOAL / DONE / REMAINING / NEXT checkpoints (Lethe): fits the unattended supervisor
- Recipes / portable workflows (Goose): fits skills export
- Desktop app packaging (Letta, Goose): Tauri wrapper for the shell later
