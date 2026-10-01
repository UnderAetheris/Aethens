# Roadmap

| Phase | Goal | Specs | Exit criteria |
| --- | --- | --- | --- |
| **0.9 Stabilize** | Green CI on main; tidy root (git mv living spec + reports) | F24 | All CI jobs green |
| **1 Brain** | Works on the owner's laptop with free models | F01, F13 | Router with Gemini/Groq/OpenRouter fallback, budgets, cache, redaction; deterministic path works with no provider |
| **2 Durable core** | Backlog and learning survive restarts | F02, F08 | Persistent queue with priority/retries; keywords persisted; `revert_last()` |
| **3 Trust** | New powers can exist safely | F04 | Tiers T0-T3, approvals inbox API, protected path list enforced |
| **4 Product shell** | Feels like a real product | F26 M1-M3 | Design system, sidebar layout, Ctrl+K, live SSE feed |
| **5 Knows you** | Personal | F06, F00 | Profile store (owner-only writes), persona rules + tests |
| **6 Shows growth** | Proof visible | F21, F07 | `coding_tasks_v1` benchmark, daily/weekly reports, Level scorecard UI |
| **7 Curious** | Finds its own weaknesses | F16, F25 | Objectives queue, gate beats random selection |
| **8 AFK** | Learns while you're away | F17, F18 | After owner amends non-goal; gated sessions, proposals only |
| **9 Care** | Looks after the PC | F19, F20 | Guardian read-only v0, vault for keys |
| **10 Evolves** | Writes its own code safely | F14 | Sandbox patches as PRs on `agent/*`, owner merges, auto-revert on regression |
| **1.0** | Public release | all | Onboarding < 10 min, installer, docs site |

Parallel track from Phase 3: F26 M4-M7 screens as backends land.
