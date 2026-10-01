# Security Policy

Aetheris runs on the owner's personal machine with access to files, commands, and the network. Security is a product feature, not an afterthought.

## Reporting

Open a private security advisory on GitHub (Security -> Advisories -> Report a vulnerability). Do not open public issues for vulnerabilities.

## Security model (summary)

- **One execution gate:** `SafetyLayer.run()` with deny-wins rules, safe mode on by default.
- **One egress gate:** `NetworkPerimeter.fetch()` (allowlist, HTTPS only, budgets, robots, no auth/cookies/JS) plus the registered model-provider boundary.
- **Permission tiers** (spec F04): read, reversible write, ask-first, never.
- **Hard locks:** the agent cannot modify safety, perimeter, evaluation gates, ledgers, or CI.
- **Prompt injection:** all external content is treated as data. Tests assert injected instructions change nothing.
- **Secrets:** never committed, never logged, never sent to model providers (spec F20 vault + redaction).
- **Local only:** the API binds to `127.0.0.1`.

Full threat model: [docs/engineering/THREAT_MODEL.md](docs/engineering/THREAT_MODEL.md).

## Supported versions

Only `main` is supported during pre-1.0 development.
