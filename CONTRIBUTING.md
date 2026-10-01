# Contributing

Aetheris is built in small, gated, reversible steps. Humans and AI agents follow the same process. Agents: read [AGENTS.md](AGENTS.md) first.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |  macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
cd shell && npm install
```

Full Windows guide for low-spec machines: [docs/engineering/DEV_SETUP_WINDOWS.md](docs/engineering/DEV_SETUP_WINDOWS.md).

## Branches

| Prefix | Use |
| --- | --- |
| `feat/<fxx>-<slug>` | New capability tied to a spec |
| `fix/<slug>` | Bug fix |
| `docs/<slug>` | Docs only |
| `chore/<slug>` | Tooling, cleanup, CI |
| `agent/<id>` | Changes proposed by Aetheris itself (F14) |

## Commits

Conventional style: `feat(research): ...`, `fix(safety): ...`, `docs(specs): ...`, `test(...)`, `chore(...)`. Imperative, under 72 chars.

## Before opening a PR

```bash
ruff check src/ tests/ scripts/
python -m pytest tests/ -q
python scripts/check_architecture_integrity.py --check
cd shell && npm test && npm run build
```

Fill in the PR template. One concern per PR. Squash-merge on green CI.

## Review checklist

- [ ] Spec exists and is updated
- [ ] No new execution or egress path
- [ ] Authority/capability ledgers updated if needed
- [ ] New flags default-off with byte-identical off-path test
- [ ] Tests cover happy path, failure path, and adversarial safety path
- [ ] UI follows the design system and UX checklist
- [ ] `CHANGELOG.md` and `handoff/CURRENT_STATE.md` updated
