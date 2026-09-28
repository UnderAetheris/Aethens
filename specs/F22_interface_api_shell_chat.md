# F22: Interface: API bridge, shell, chat

**Status:** API bridge `built` (default-off), React shell `built` (unmeasured), chat `proposed`
**Module:** `src/aetheris/api/`, `shell/`

## 1. Purpose
How the owner talks to Aetheris and approves things.

## 2. Current state
FastAPI bridge (`uvicorn aetheris.api.app:app`), read-only status endpoints (`/reasoning/*`, `/research/status`, `/session/*`), React shell polling every 1s.

## 3. Additions
- **Chat:** `POST /chat` -> task submission + conversational reply via router (F13); persona rules (F00)
- **Approvals inbox:** `GET /approvals`, `POST /approvals/{id}/approve|deny` (F04)
- **Toggles (owner only):** AFK on/off, Guardian on/off (writes profile, not config)
- **Feedback:** thumbs up/down + correction text -> curiosity signal (F16)
- **Reports view:** F21
- Bind to `127.0.0.1` only; local auth token for the shell

## 4. Rules
No endpoint raises budgets, forces steps past health checks, or triggers egress directly.

## 5. Tests
`test_api_binds_localhost_only`, `test_approval_endpoint_requires_owner_token`, `test_no_endpoint_raises_budget`.
