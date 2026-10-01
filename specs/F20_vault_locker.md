# F20: Vault (secrets locker)

**Status:** proposed; **owner to confirm meaning of "locker"**
**Default:** off
**Module:** `src/aetheris/vault/` (new)

## 1. Interpretation
Assumed: a local encrypted locker for API keys (F13), tokens, and sensitive notes, so secrets never sit in plain `.env` or reach model prompts. Alternatives the owner may have meant: folder locker, app lock, PC lock. Update this spec after confirmation.

## 2. Design
- Windows DPAPI (per-user encryption, no extra password) via `keyring` library; fallback passphrase + `cryptography` Fernet
- Scopes: `provider:gemini`, `provider:groq`, ..., `note:<name>`
- `vault_get(scope)` is T2 for notes, T1 for provider keys only when called by the model router
- Secrets never logged; redaction filter on all outbound prompts and reports

## 3. Authority
read/write own encrypted store only (`persistence.vault`, new boundary). No network.

## 4. Adoption gate
Secret-leak suite: planted secrets never appear in logs, prompts, reports, evidence records.

## 5. Tests
`test_secret_never_in_event_log`, `test_secret_redacted_in_prompt`, `test_note_read_requires_approval`.
