# F01: Runtime & hardware profile ($0, low-end laptop)

**Status:** proposed
**Default:** n/a (deployment profile)
**Depends on:** F13

## 1. Purpose

Make Aetheris run well on the owner's actual machine at zero cost beyond the AI coding agent already paid for.

## 2. Target machine

| Spec | Value | Consequence |
| --- | --- | --- |
| CPU | i5-8365U, 4c/8t, 1.6-1.9 GHz | Fine for Python core, tests, AST scans |
| RAM | 8 GB (7.8 usable) | No Docker Desktop; cap WSL2; no local 7B+ models |
| GPU | Intel UHD 620, 128 MB | No local GPU inference |
| Disk | ~313 GB free | Plenty for journals, caches, snapshots |
| OS | Windows 64-bit | Guardian (F19) targets Windows; core stays cross-platform |

## 3. Decision: laptop = body, cloud = brain

- **Local:** controller, executive, safety, tools, memory stores, evaluation, learning, research perimeter, supervisor, API bridge, shell.
- **Model calls:** free-tier hosted models via `ApiProvider` behind `network_egress.model_provider` (F13 router).
- **Optional local model:** Ollama with a 1.5B-3B model (e.g. Qwen2.5 1.5B/3B) for cheap classification/summaries only. Never the primary brain.
- **Heavy experiments:** Kaggle / Colab free notebooks, results imported as evidence records, never direct access to the live tree.

## 4. Environment

- Python 3.12 venv (`pip install -e ".[dev]"`), Node for `shell/`.
- Sandbox for patch validation: existing temp-dir sandbox (`sandbox_validation.model_patch`). Optional WSL2 with `.wslconfig` `memory=3GB`, `processors=2`.
- No Docker Desktop (RAM cost too high).
- Resource budget for the Aetheris process: target < 1.5 GB RSS idle, < 3 GB under eval.

## 5. Resource guard (proposed)

A read-only sampler feeding the Unattended watchdog (F18):

- pause AFK/unattended work when on battery below 30%, CPU > 85% for 60s, free RAM < 1 GB, or the owner is active (optional)
- never kill owner processes

## 6. Costs

| Item | Cost |
| --- | --- |
| Python, git, pytest, ruff, SQLite, ChromaDB (if adopted), Playwright | free |
| Gemini (AI Studio), Groq, OpenRouter free models | free tier, rate-limited, terms change |
| GitHub Actions (public repo or free minutes) | free within limits |

## 7. Risks

- Free tiers change or vanish -> router must degrade to "local tiny model + deterministic path" and report it, never crash.
- Free tiers may log prompts -> never send secrets (F20) or private files without owner opt-in.
- 8 GB RAM -> eval suites must stay streaming/hermetic; no loading big corpora into memory.

## 8. Tests

- `test_runs_with_no_model_provider_configured` (deterministic path still works)
- `test_resource_guard_pauses_on_low_memory`
- `test_no_secret_in_outbound_prompt`
