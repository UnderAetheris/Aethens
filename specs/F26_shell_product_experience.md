# F26: Shell product experience (UI/UX)

**Status:** proposed (thin shell `built`; product UI not yet)
**Default:** n/a
**Module:** `shell/`
**Depends on:** F02, F04, F21, F22; design docs in `docs/design/`

## 1. Purpose

Turn the thin polling client into a calm, fast, beautiful product people want to open every day. Must not look or feel vibecoded.

## 2. Scope

Screens, states, and data are defined in `docs/design/SCREENS.md`. Visual language in `docs/design/DESIGN_SYSTEM.md`. Rules in `docs/design/UX_PRINCIPLES.md`.

## 3. Tech decisions

| Concern | Choice | Why |
| --- | --- | --- |
| Framework | React 18 + Vite + TS strict (existing) | Already in repo |
| Routing | React Router | Standard, small |
| Data | TanStack Query over the API client | Cache, retries, optimistic updates |
| Live updates | SSE `/events/stream` (fallback: polling) | Cheaper than 1s polling, simpler than websockets |
| Motion | Framer Motion | Declarative, reduced-motion support |
| Styling | CSS variables + CSS modules | Zero runtime cost, tokens enforced |
| Icons | Lucide | Consistent, light |
| Command palette | cmdk | Proven UX |
| Desktop (later) | Tauri | Small footprint for 8 GB machines |

## 4. Milestones

1. **M1 Tokens + primitives**: tokens.css, Button, Card, Badge, StatusDot, Skeleton, EmptyState, ErrorState, Toast
2. **M2 Layout**: router, Sidebar, CommandPalette, Home v0 from current widgets
3. **M3 Live**: SSE stream + ActivityFeed with expandable "why"
4. **M4 Approvals**: ApprovalCard + inbox (needs F04 backend)
5. **M5 Chat**: streaming chat with inline plans (needs F22 backend)
6. **M6 Onboarding**: first-run wizard < 10 min
7. **M7** Memory, Skills, Research, Guardian, Reports, Settings

## 5. Quality gates

- Vitest coverage on components >= 80%
- Lighthouse (local build) performance >= 90, accessibility >= 95
- Bundle < 250 KB gzip for initial route
- Every screen: five states + keyboard path + reduced motion

## 6. Security

- API base URL from env, localhost only; local auth token header
- No secrets in the browser bundle; vault access only server-side

## 7. Tests

`ApprovalCard approves with A key`, `ActivityFeed anchors scroll on insert`, `CommandPalette opens with Ctrl+K`, `reduced motion disables transforms`.
