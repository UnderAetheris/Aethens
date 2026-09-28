# F13: Model providers & free-tier router

**Status:** providers `built` (default-off); router `proposed`
**Default:** off
**Module:** `src/aetheris/model/`
**Boundary:** `network_egress.model_provider`

## 1. Purpose
Give Aetheris a brain on a laptop with no GPU, at $0, without making any single provider a dependency.

## 2. Current state
`LocalProvider` and `ApiProvider` with injectable `transport`; model comparison tests; planner-with-model; model-assisted patching.

## 3. Router design
```
ModelRouter(providers=[...], policy)
  complete(role, prompt, max_tokens) -> ModelResult | Abstain
```
- Providers (config, owner-supplied keys from F20): Gemini (AI Studio free), Groq free, OpenRouter `:free` models, optional local Ollama 1.5B-3B
- Per-provider budgets: requests/min, requests/day, tokens/day (tracked locally, conservative)
- Role routing: `plan` / `patch` / `summarize` / `classify` -> preferred provider list
- Fallback on 429/5xx/timeout to next provider; if all fail -> `Abstain` and deterministic path continues
- Response cache keyed by prompt hash (saves free quota)

## 4. Privacy rules
- Redact secrets and anything under non-approved paths before sending
- Owner setting: which roles may use which providers
- Log provider, model, token counts, latency; never log full prompts containing profile data

## 5. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| reach_network | direct (operator-configured endpoints only) | network_egress.model_provider |
| everything else | none (model output is advisory text) | |

## 6. Adoption gate
Coding suite completion with router >= single-provider baseline; zero crashes on simulated provider outage; budget never exceeded.

## 7. Rollback
`config_disable`.

## 8. Risks
Free tiers change; quality varies by model -> model comparison harness re-run weekly (owner-triggered).

## 9. Tests
`test_fallback_on_429`, `test_all_down_abstains`, `test_daily_budget_enforced`, `test_secrets_redacted_before_send`, `test_cache_hit_skips_network`.
