# Design system v0.1

Goal: feels like Linear, Raycast, and Arc had a calm, trustworthy child. Dark-first, quiet, fast, precise. Every pixel earns its place.

## 1. Tokens

Implement as CSS custom properties in `shell/src/styles/tokens.css`. Components never use raw hex.

### Color (dark, default)

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#0B0D12` | App background |
| `--surface-1` | `#11141B` | Sidebar, cards |
| `--surface-2` | `#1A1F2A` | Hover, inputs, secondary buttons |
| `--border` | `#232938` | Card borders, dividers |
| `--text-1` | `#F2F4F8` | Primary text |
| `--text-2` | `#A7AEBD` | Secondary text |
| `--text-3` | `#6B7385` | Meta, timestamps |
| `--accent` | `#7C5CFF` | Primary actions, focus, Aetheris identity |
| `--accent-hover` | `#8F74FF` | |
| `--success` | `#2BD9A0` | Passed, healthy, allowed |
| `--warning` | `#FFB547` | Needs attention, pending approval |
| `--danger` | `#FF5C7A` | Failed, blocked, threats |
| `--info` | `#4CB4FF` | Research, links |

Light theme mirrors the scale (bg `#F7F8FA`, surface `#FFFFFF`, text `#0B0D12`). Contrast: all text >= WCAG AA 4.5:1.

**Semantic rule:** color always carries meaning the same way. Purple = Aetheris acting/your action. Green = safe/passed. Amber = needs you. Red = failed/blocked. Never decorative.

### Type

- Font: Inter (UI), JetBrains Mono (code, IDs, diffs). Self-host, no CDN.
- Scale (px): 12 meta, 13 dense, 14 body, 16 emphasis, 20 section, 26 page title, 40 hero metric.
- Weights: 400, 500, 600, 700 only. Line height 1.45 body, 1.2 headings.
- Numbers: `font-variant-numeric: tabular-nums` everywhere metrics appear.

### Space, radius, elevation

- Space scale 4/8/12/16/20/24/32/48.
- Radius: 8 controls, 12 small cards, 16 cards, 999 pills.
- Elevation by surface color, not shadows. One shadow for floating layers (`0 12px 40px rgba(0,0,0,.45)`): command palette, menus, toasts.

## 2. Motion

Motion explains state change, never decorates.

| Token | Duration | Easing | Use |
| --- | --- | --- | --- |
| `--motion-fast` | 120ms | `cubic-bezier(.2,.8,.2,1)` | hover, press, toggles |
| `--motion-base` | 200ms | same | panels, list insert, tabs |
| `--motion-slow` | 320ms | `cubic-bezier(.16,1,.3,1)` | page transitions, palette open |

Patterns:
- New activity rows slide in 8px + fade; never shift content the user is reading (anchor scroll).
- Approve/deny: button morphs to check/cross, card collapses 200ms, toast with **Undo** for 6s.
- Level up: number ticks up with tabular digits, progress bar fills, one subtle accent glow. Once. No confetti spam.
- Skeletons shimmer max 1.2s loop; show real content within 300ms where possible.
- `prefers-reduced-motion`: replace all movement with opacity, no shimmer.

Library: Framer Motion (`motion`) for React. No animation in CSS for anything stateful.

## 3. Components (build order)

1. `Button` (primary, secondary, ghost, danger; sizes sm/md; loading state)
2. `Card`, `Badge`, `StatusDot`, `Pill`
3. `Sidebar` + `NavItem` (with count badge)
4. `CommandPalette` (Ctrl/Cmd+K: ask, jump, run skill, toggle AFK)
5. `ActivityFeed` row (status dot, text, time, expand for details/why)
6. `ApprovalCard` (action, tier badge, diff/preview, undo plan, approve/deny, keyboard A/D)
7. `MetricTile`, `ProgressBar`, `Sparkline`
8. `Toast` with action
9. `EmptyState`, `ErrorState`, `Skeleton`
10. `DiffViewer`, `CodeBlock`
11. `ChatThread` + `Composer` (streaming, stop, attach)
12. `Toggle`, `Select`, `Input`, `Textarea`

Every component ships with: keyboard support, visible focus ring (`2px var(--accent)` offset 2), aria labels, loading/empty/error variants, a Vitest test, and reduced-motion behavior.

## 4. Iconography

Lucide icons, 16px in UI / 20px in nav, 1.5 stroke. No emoji in product UI.

## 5. Voice in UI copy

- Short, human, specific: "Cleaned 2.3 GB. Undo?" not "Operation completed successfully."
- Numbers over adjectives: "pass rate 71% to 74%" not "improved a lot".
- Honest when it fails: "I couldn't verify this, here's why."
- Never cute in errors or security warnings.
