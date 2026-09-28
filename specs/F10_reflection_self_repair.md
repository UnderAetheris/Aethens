# F10: Reflection & self-repair

**Status:** `built` (reflection default-on, code repair loop, self_repair adopted)
**Default:** reflection on; `code_loop_enabled` off (`AETHERIS_CODE_LOOP=1`)
**Module:** `src/aetheris/reflection/`

## 1. Purpose
When a step fails, diagnose and propose a bounded repair inside the plan. This is "repairs itself" at task level.

## 2. Current state
ReflectionEngine returns verdicts; Executive enacts. Repair budget bounded. Uses Understanding facts (`exporting_module`, `find_helper`) and reasoning advice.

## 3. Self-repair of the system (health level)
Distinct from task repair. When the system itself degrades:
1. Watchdog (F18) detects: failing self-tests, corrupted journal, provider outage, disk full
2. Classify: config / data / code / environment
3. Remedy ladder: retry -> fall back (e.g. provider router) -> restore from snapshot -> propose code fix via F14 -> stop and report
4. Never patch protected paths; never continue past unrecoverable fault

## 4. Adoption gate (code loop default-on)
Coding suite: completion up, repairs per task down, zero unsafe attempts, zero regressions.

## 5. Tests
`test_corrupt_journal_restores_snapshot`, `test_provider_outage_falls_back`, `test_self_repair_never_touches_protected_paths`.
