# F19: Guardian: Windows health & security

**Status:** proposed
**Default:** off
**Module:** `src/aetheris/guardian/` (new)
**Depends on:** F04 tiers, F05 tools, F21 reports

## 1. Purpose
Keep the owner's Windows PC healthy and give plain-English security visibility. **Complements Windows Defender, never replaces it.**

## 2. Abilities

### v0 read-only (T0)
- Health: disk free, RAM pressure, CPU, battery health, uptime, pending Windows Updates
- Security visibility: Defender status + threat history (`Get-MpComputerStatus`, `Get-MpThreatDetection`), firewall on/off, SmartScreen blocks from event logs
- Audits: startup items, scheduled tasks, services set to auto, listening ports + owning process, recently installed programs
- Diff vs last baseline: "3 new startup items since last week"
- Browser safety: surface Defender/SmartScreen web-block events and tell the owner which tab/site; no traffic inspection

### v1 ask-first (T2)
- Temp/cache cleanup with size preview
- Organize Downloads/Desktop into folders by rule, with undo manifest
- Disable a startup item the owner selects (reversible)
- Trigger a Defender quick scan (`Start-MpScan -ScanType QuickScan`)

### never (T3)
Disable Defender/firewall/UAC, edit System32, delete registry keys, kill unknown system processes, install drivers, anything requiring stored admin credentials.

## 3. Design
- Fixed PowerShell templates (typed args) wrapped as tools (F05)
- Scheduler: health sample every 30 min when enabled, full audit daily
- Baseline store (`persistence.guardian_baseline`, new boundary) for diffs
- Alerts: urgent (Defender threat found, firewall off) -> immediate notification; everything else -> daily report

## 4. Realistic limits (stated honestly)
- Cannot detect "a website under cyber attack" in real time; relies on Defender/SmartScreen/browser signals
- Not an antivirus; no signatures, no heuristics engine
- Needs no admin for v0; some v1 actions need an elevated prompt the owner accepts manually

## 5. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| read_files (system logs, outside workspace) | direct, read-only | execution.safety_layer (T0 tools) |
| execute_commands | direct, fixed templates only | execution.safety_layer |
| write_files outside workspace | delegated via T2 approval | execution.safety_layer |
| reach_network | none | |

## 6. Adoption gate
`guardian_v1` fixture logs: detection recall >= 0.9 on planted suspicious startup/tasks, false alarm rate <= 0.1, zero T3 attempts, every T2 action has an undo manifest.

## 7. Rollback
`config_disable`; T2 actions each carry an undo manifest (moved files list, disabled item restore).

## 8. Risks
- False alarms erode trust -> explain evidence, allow "mark as known good"
- Privacy: logs contain personal data -> never sent to model providers without redaction + owner opt-in

## 9. Tests
`test_guardian_off_no_system_reads`, `test_t3_guardian_actions_denied`, `test_cleanup_preview_matches_execution`, `test_organize_has_undo_manifest`, `test_system_logs_redacted_before_model`.

## 10. Open questions
Owner to confirm the T2 vs T3 split above.
