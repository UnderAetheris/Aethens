# Screens

Wireframe of Home: [assets/app-shell-wireframe.svg](assets/app-shell-wireframe.svg).

Layout: left sidebar (232px) + top command bar + content. Sidebar collapses to icons under 1100px.

| # | Screen | Purpose | Key components | Data (API) | Spec |
| --- | --- | --- | --- | --- | --- |
| 1 | **Onboarding** | Install to first win in < 10 min: welcome, choose providers, paste free key (stored in vault), pick approved folders, run sample task | Stepper, provider cards, folder picker | `/setup/*` (new) | F01, F13, F20 |
| 2 | **Home** | "N things need you", overnight summary, Level, PC health, live activity, goals | ApprovalCard, MetricTile, ActivityFeed | `/session/status`, `/approvals`, `/reports/latest` | F21 |
| 3 | **Chat** | Talk, give tasks, see live plan + safety decisions inline, ask "why?" | ChatThread, Composer, inline PlanCard | `/chat`, `/tasks` | F22 |
| 4 | **Tasks & Goals** | Queue, long-term goals as DAGs, progress, pause/resume | Board/List toggle, GoalGraph | `/tasks`, `/goals` | F02, F03 |
| 5 | **Approvals** | Inbox of ask-first actions with preview + undo plan | ApprovalCard list, DiffViewer | `/approvals` | F04 |
| 6 | **Memory** | Browse/search/edit lessons, knowledge, profile; see versions | Search, MemoryItem, VersionHistory | `/memory/*` | F06 |
| 7 | **Skills** | Library: active/held/retired, metrics, history, promote/retire (approval) | SkillCard, Sparkline | `/skills` | F09 |
| 8 | **Research** | Evidence bundles, citations, contradictions, source reliability | EvidenceCard, CitationList | `/research/*` | F15 |
| 9 | **Guardian** | PC health, Defender status/history, startup/tasks/network audits, cleanup proposals | HealthTiles, AuditTable | `/guardian/*` | F19 |
| 10 | **Reports & Level** | Daily/weekly/AFK reports, scorecard per benchmark, history | ReportView, Scorecard | `/reports/*` | F21 |
| 11 | **Settings** | Providers, budgets, AFK hours + allowlist, approved folders, theme, data export/reset | Forms, Toggles | `/profile` | F06, F17 |

## Current shell vs target

Today `shell/src/App.tsx` is a single grid: Composer, Indicators, QueueList, TaskDetail, ActivityLog, polling every 1s. It is a working thin client but not the product UI. Migration plan:

1. Introduce tokens + design system components (no behavior change)
2. Add router (React Router) + Sidebar layout; current grid becomes Home v0
3. Replace 1s polling with SSE (`/events/stream`) behind a flag, fall back to polling
4. Build Approvals and Chat (needs F04 and F22 backend)
5. Remaining screens as their backends land
