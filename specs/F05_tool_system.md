# F05: Tool System

**Status:** `built`
**Default:** on
**Module:** `src/aetheris/tools/`

## 1. Purpose
Leaf capabilities with honest metadata. Tools perform side effects; nothing else does.

## 2. Current state
Registry; tools expose `safe` flag and optional `undo`. read/list/echo safe; write/shell unsafe; shell declares no undo.

## 3. Tool contract (extended)
```
name, description, tier (F04), safe: bool,
inputs schema, outputs schema,
side_effects: [files|process|network|system],
undo: callable | None, dry_run: callable,
platform: any|windows|posix, timeout_s, max_output_bytes
```

## 4. Planned tools
| Tool | Tier | For |
| --- | --- | --- |
| `run_tests` (pytest allowlisted) | T1 | code loop |
| `git_status/diff/branch/commit` | T1 (commit on agent branch only) | F14 |
| `win_health_sample` | T0 | F19 |
| `win_defender_history` (`Get-MpThreatDetection`, read) | T0 | F19 |
| `win_startup_list`, `win_scheduled_tasks_list`, `win_net_connections` | T0 | F19 |
| `fs_organize` (move within approved roots) | T2 | F19 |
| `temp_cleanup` | T2 | F19 |
| `vault_get` | T2 per secret scope | F20 |

No tool may perform network egress; that stays in the perimeter / model boundary.

## 5. Rules
- New tool = new registry entry + authority ledger entry + tests + CI tripwire pass
- PowerShell commands are fixed templates with typed args, never free-form strings

## 6. Tests
`test_every_tool_declares_tier`, `test_powershell_tools_use_fixed_templates`, `test_no_tool_imports_network_libs`.
