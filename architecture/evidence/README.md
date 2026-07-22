# Evidence Directory

This directory contains machine-readable evidence records for adopted/default-on capabilities.

## File naming

Each file is named `<capability_id>-v0.json`.

## Record schema

```json
{
  "schema_version": 1,
  "capability_id": "research",
  "revision": "<SHA or WORKTREE>",
  "recorded_at": "<UTC ISO-8601>",
  "configuration": { "...": "..." },
  "benchmark": {
    "id": "research-wide-v0",
    "command": "python scripts/run_research_wide_gate.py",
    "implementation_paths": [ "src/aetheris/research/benchmark.py" ]
  },
  "raw_metrics": {
    "completion_off": {"value": null, "observed": false, "reason": "not emitted by captured run"},
    "unsafe_requests": {"value": 0, "observed": true, "observation_count": 10}
  },
  "gate": {
    "verdict": "pass",
    "exit_code": 0,
    "output_sha256": "<hash of captured raw output>",
    "artifact": "<CI artifact name or checked evidence path>"
  },
  "rollback_token": "config:research_enabled=false",
  "limitations": []
}
```

## Rules

- `null` means unknown. Never replace missing metrics with zero or a fabricated value.
- A numeric zero is allowed only when a command actually ran, emitted that metric, and the evidence record identifies the run.
- Placeholder tokens such as `TBD`, `TODO`, `N/A`, `example`, `fake`, or `<SHA>` are forbidden in committed records.
- A rollback token is an identifier/instruction, never a credential.

## Limitations

Evidence capture in v0 records only what the benchmark output actually contains. Missing metrics are `null`. The checker does not parse human prose.
