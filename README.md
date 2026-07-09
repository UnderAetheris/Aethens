# Aetheris

A modular agent system. This is v0.1: the walking skeleton.

## Quickstart
```bash
pip install -e ".[dev]"
python -m aetheris "do the thing"
pytest
```

## Architecture
The Controller receives a task, logs it to Memory, selects a Tool from the
registry, runs it, and logs the result. Each subsystem lives in its own package
under `src/aetheris/` so they plug in without tangling.

| Package | Role | Status |
| ---| ---| --- |
| controller | Receives and routes tasks | minimal |
| tools | Registry of safe actions | minimal |
| memory | Task history + lessons (JSONL) | minimal |
| planner | Chooses tools/steps for a task | stub |
| skills | Reusable higher-level capabilities | stub |
| evaluation | Benchmarks + scoring | stub |
| research | Information gathering | stub |
| learning | Self-improvement loop | stub |
| safety | Guards, logging, reversibility | stub |

## Contributing
1. `pre-commit install`
2. Branch, code, `pytest` green, open a PR.
3. CI runs ruff + pytest on every push/PR.
