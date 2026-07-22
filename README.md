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

Every ordinary registered tool action executes through `SafetyLayer`; network egress, internal persistence, and isolated sandbox validation use separately declared boundaries.

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
<!-- architecture-capabilities:end -->


## Contributing
1. `pre-commit install`
2. Branch, code, `pytest` green, open a PR.
3. CI runs ruff + pytest + coverage + architecture-integrity + repository-integrity + specialized gates (research, reasoning, hierarchy, reliability, unattended) on every push/PR. Lint, test, and specialized gates run independently; a lint failure does not skip tests.
