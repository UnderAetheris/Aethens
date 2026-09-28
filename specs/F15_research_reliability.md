# F15: Research Engine + source reliability

**Status:** `built`; research default-on; reliability consumption default-on
**Module:** `src/aetheris/research/`
**Boundary:** `network_egress.research_perimeter`

## 1. Purpose
Gather immutable, cited evidence from allowlisted sources. Information increases; authority does not.

## 2. Current state
`Query -> Search -> Fetch -> Extract -> Validate -> Cite -> EvidenceBundle`. `NetworkPerimeter`: allowlist, HTTPS-only, redirect caps, budgets, robots, MIME, no auth/cookies/JS, dry-run, task-scoped. Honesty axes (contradictions, freshness, abstention) all 1.0. Reliability learns source trust but never gates coverage. Absolute unsafe-request clause in CI.

## 3. Next
- Widen allowlist in measured steps: official docs (python.org, docs of libs we use), GitHub release notes, arXiv abstracts, selected AI news sites (for F17)
- Feed reliability into Experience (retire domain trust, reversible)
- Research summaries store (F06)
- Prompt-injection fixtures: pages containing instructions must yield zero plan/action changes

## 4. Rules (forever)
No new egress path, no auth/cookies/JS, no write-back to the web, research informs never does.

## 5. Tests to add
`test_page_with_injected_instructions_changes_nothing`, `test_allowlist_widening_requires_gate_rerun`.
