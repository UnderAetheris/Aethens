# Aetheris

**The personal AI that actually gets better at helping you, and proves it.**

Aetheris is a modular, self-improving assistant and engineering system. It plans work, acts only through a single safety gate, measures itself on frozen benchmarks, and keeps an improvement only when it is strictly better with zero regressions and can be undone. It is designed to run on an ordinary Windows laptop for free.

```
plan -> act safely -> measure -> record -> improve
```

## Why Aetheris

- **Proven improvement**: every learned change passes a measured gate and leaves a rollback receipt.
- **Visible safety**: one execution gate, one network gate, permission tiers, hard locks the system can never cross, all enforced in CI.
- **Personal**: remembers your preferences and projects, explains every decision, reports what it learned.
- **Light and free**: no GPU, no Docker, free-tier models behind a fallback router.

## Quick start

```bash
pip install -e ".[dev]"
python -m uvicorn aetheris.api.app:app --reload

cd shell
npm install
npm run dev
```

The shell reads the backend URL from `shell/.env` and talks to the FastAPI bridge.

Windows / low-spec guide: [docs/engineering/DEV_SETUP_WINDOWS.md](docs/engineering/DEV_SETUP_WINDOWS.md).

## Repository guide

| Path | What |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Operating manual for AI coding agents and contributors |
| [`specs/`](specs/README.md) | Per-feature specs F00-F26 and the full inventory |
| [`docs/`](docs/README.md) | Product, design system, architecture diagrams, engineering guides |
| [`handoff/`](handoff/README.md) | Session continuity: state, decisions, roadmap, conversation log |
| [`architecture/`](architecture/ARCHITECTURE_BASELINE.md) | Machine-checked ledgers, contracts, evidence |
| `src/aetheris/` | Python backend, one package per subsystem |
| `shell/` | React + Vite + TypeScript UI |
| `tests/`, `scripts/` | Test suites, gate runners, integrity checker |

## Architecture

The Controller receives a task, logs it to Memory, selects a Tool from the
registry, runs it, and logs the result. Each subsystem lives in its own package
under `src/aetheris/` so they plug in without tangling.

Every ordinary registered tool action executes through `SafetyLayer`; network egress, internal persistence, and isolated sandbox validation use separately declared boundaries.

Diagrams: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md).

<!-- architecture-capabilities:start -->
| Capability | Implementation | Measurement | Adoption | Runtime Default | Production Readiness |
| --- | --- | --- | --- | --- | --- |
| config | complete | measured | adopted | on | unknown |
| tools | complete | measured | adopted | on | unknown |
| safety | complete | measured | adopted | on | unknown |
| controller | complete | measured | adopted | on | unknown |
| planner | complete | measured | adopted | on | unknown |
| executive | complete | measured | adopted | on | unknown |
| memory | complete | measured | adopted | on | unknown |
| evaluation | complete | measured | adopted | on | unknown |
| skills | complete | measured | adopted | on | unknown |
| skill_promotion | complete | measured | adopted | off | unknown |
| plan_review | complete | measured | adopted | on | unknown |
| reflection | complete | measured | adopted | on | unknown |
| autonomous_loop | partial | measured | adopted | on | unknown |
| self_repair | complete | measured | adopted | on | unknown |
| model_providers | complete | measured | adopted | off | unknown |
| model_patch | complete | measured | adopted | off | unknown |
| understanding | complete | measured | adopted | off | unknown |
| reasoning | complete | measured | adopted | on | unknown |
| experience_recording | complete | measured | adopted | on | unknown |
| experience_consumption | complete | measured | hold | off | unknown |
| hierarchy | complete | measured | adopted | off | unknown |
| research | complete | measured | adopted | on | unknown |
| research_reliability | complete | measured | adopted | on | unknown |
| api_bridge | complete | measured | adopted | off | unknown |
| unattended_supervisor | complete | measured | adopted | off | unknown |
| unattended_outcome_learning | complete | measured | hold | off | unknown |
| frontend_shell | complete | unmeasured | not_applicable | off | unknown |
| trace_replay | complete | measured | adopted | not_applicable | unknown |

<!-- architecture-capabilities:end -->


## Contributing
1. `pre-commit install`
2. Branch, code, `pytest` green, open a PR.
3. CI runs ruff + pytest + coverage + architecture-integrity + repository-integrity + specialized gates (research, reasoning, hierarchy, reliability, unattended) on every push/PR. Lint, test, and specialized gates run independently; a lint failure does not skip tests.

Full guide: [CONTRIBUTING.md](CONTRIBUTING.md). Security: [SECURITY.md](SECURITY.md).
