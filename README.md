# Aetheris

A modular agent system with a FastAPI bridge and a thin React shell.

## Backend

Start the API bridge:

```bash
pip install -e ".[dev]"
python -m uvicorn aetheris.api.app:app --reload
```

## Frontend shell

Install and run the shell:

```bash
cd shell
npm install
npm run dev
```

The shell reads the backend URL from shell/.env and polls the FastAPI bridge every second.

## Architecture
The Controller receives a task, logs it to Memory, selects a Tool from the
registry, runs it, and logs the result. Each subsystem lives in its own package
under `src/aetheris/` so they plug in without tangling.

| Package | Role | Status |
| ---| ---| --- |
| controller | Receives and routes tasks | complete |
| tools | Registry of safe actions | complete |
| memory | Task history + lessons (JSONL) | complete |
| planner | Chooses tools/steps for a task | complete |
| skills | Reusable higher-level capabilities | stub |
| evaluation | Benchmarks + scoring | complete |
| research | Information gathering (default-off, gated) | gated |
| learning | Self-improvement loop + session telemetry | complete |
| safety | Guards, logging, reversibility | complete |
| api | FastAPI bridge for the shell | complete |
| unattended | Bounded fail-closed supervisor (default-off, gated) | gated |

## Contributing
1. `pre-commit install`
2. Branch, code, `pytest` green, open a PR.
3. CI runs ruff + pytest + coverage + repository-integrity + specialized gates (research, reasoning, hierarchy, reliability, unattended) on every push/PR. Lint, test, and specialized gates run independently; a lint failure does not skip tests.
