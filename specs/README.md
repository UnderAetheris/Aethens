# Aetheris Feature Specs

One file per feature. Each spec is the contract for that feature: what it does, what it may touch, how we prove it helps, and how we undo it.

The [living architecture spec](../Aetheris%20Architecture%20v1.0%20(living%20spec)-20260709161540.md) and [`architecture/ARCHITECTURE_BASELINE.md`](../architecture/ARCHITECTURE_BASELINE.md) stay the tiebreakers. If a feature spec contradicts them, the spec is wrong until the architecture doc is amended first.

## Status legend

| Status | Meaning |
| --- | --- |
| `built` | Code + tests exist in `src/aetheris/`, listed in `architecture/capabilities.json` |
| `partial` | Exists but incomplete (must stay `partial` in the ledger) |
| `proposed` | Designed here, no code yet. Needs gate + authority registration before build |
| `needs-decision` | Conflicts with a current non-goal or invariant. Owner must decide before build |

## Index

| ID | Feature | Status | Default |
| --- | --- | --- | --- |
| [F00](F00_vision_principles_manners.md) | Vision, principles, manners & persona | proposed (persona) | n/a |
| [F01](F01_runtime_hardware_profile.md) | Runtime & hardware profile ($0, low-end laptop) | proposed | n/a |
| [F02](F02_controller_executive_queue.md) | Controller, Executive, Task Queue | built / partial (queue) | on |
| [F03](F03_planner_hierarchy.md) | Planner + Hierarchical decomposition | built | planner on, hierarchy off |
| [F04](F04_safety_permissions_approvals.md) | Safety Layer, permission tiers, approvals inbox | built / proposed (tiers, inbox) | on |
| [F05](F05_tool_system.md) | Tool System | built | on |
| [F06](F06_memory_system.md) | Memory: event, knowledge, experience, user profile | built / proposed (profile) | on |
| [F07](F07_evaluation_benchmarks.md) | Evaluation Engine & benchmark suites | built | on |
| [F08](F08_learning_engine.md) | Learning Engine (lever widening) | built | on |
| [F09](F09_skills_promotion.md) | Skills, skill seeds, skill promotion | built | skills on, promotion off |
| [F10](F10_reflection_self_repair.md) | Reflection & self-repair | built | on |
| [F11](F11_reasoning_engine.md) | Deliberative reasoning | built | on |
| [F12](F12_repo_understanding.md) | Repository understanding | built | off |
| [F13](F13_model_providers_router.md) | Model providers & free-tier router | built / proposed (router) | off |
| [F14](F14_self_code_evolution.md) | Model-assisted patching & self-code evolution | built / proposed (evolution) | off |
| [F15](F15_research_reliability.md) | Research Engine + source reliability | built | on |
| [F16](F16_curiosity_engine.md) | Curiosity engine (weakness discovery) | proposed | off |
| [F17](F17_afk_learning_mode.md) | AFK learning mode | needs-decision | off |
| [F18](F18_unattended_supervisor.md) | Unattended supervisor & health watchdog | built | off |
| [F19](F19_guardian_windows.md) | Guardian: Windows health & security | proposed | off |
| [F20](F20_vault_locker.md) | Vault (secrets locker) | proposed | off |
| [F21](F21_reports_explainability.md) | Reports & explainability | proposed | on (read-only) |
| [F22](F22_interface_api_shell_chat.md) | Interface: API bridge, shell, chat | built / proposed (chat) | off |
| [F23](F23_changesets_trace_recovery.md) | Changesets, rollback receipts, trace replay, recovery drills | built | n/a |
| [F24](F24_governance_ci.md) | Governance: architecture integrity & CI gates | built | on |
| [F25](F25_mind_cognitive_architecture.md) | Mind: cognitive architecture (composition) | proposed | n/a |
| [F26](F26_shell_product_experience.md) | Shell product experience (UI/UX) | proposed | n/a |

Full list of every ability, manner and rule captured: [INVENTORY.md](INVENTORY.md).

## Recommended build order (next)

0. **Get CI green on `main`** (see `handoff/CURRENT_STATE.md`)
1. **F01** runtime profile + **F13** free-tier router
2. **F02** Task Queue v1 + **F08** persisted keywords / `revert_last()`
3. **F04** permission tiers + approvals inbox
4. **F26** M1-M3 (design system, layout, live feed) in parallel with backend work
5. **F06** user profile memory + **F00** persona
6. **F21** reports
7. **F16** curiosity engine, then **F17** AFK learning (after the non-goal decision)
8. **F19** Guardian (read-only first), **F20** vault
9. **F14** self-code evolution (last: widest lever)

## Rules every spec follows

- Every new power maps to the 10 authority dimensions and a registered boundary in `architecture/authority.json`.
- Every feature ships **default-off**, earns default-on through a measured gate, and has a rollback kind.
- Off-path must be byte-identical to the previous milestone.
- Information may increase; authority only increases through an explicit, reviewed spec change.

New spec? Copy [TEMPLATE.md](TEMPLATE.md).
