# F18: Unattended supervisor & health watchdog

**Status:** `built`, default-off (`AETHERIS_UNATTENDED=1`); `autonomous_loop` still `partial`
**Module:** `src/aetheris/unattended/`

## 1. Purpose
Drive the existing Executive one gated step at a time, fail-closed. May stop work, never expand it.

## 2. Current state
`HealthWatchdog.check`, `SessionBounds` (brakes only), quiescent checkpoints, `SessionJournal` rehydrate, `/session/*` endpoints. Gate CLEARED. Session outcome learning on hold.

## 3. Next
- Host resource signals from F01 resource guard (battery, CPU, RAM)
- Host AFK sessions (F17) as a workload shape
- Complete `autonomous_loop` (partial) scope: document exactly what remains
- Default-on only after benchmark on >= 3 long workload shapes

## 4. Rules (forever)
Powers = continue-one-gated-step / checkpoint / pause-stop. No budget raising, no network, no tool.

## 5. Tests to add
`test_low_battery_pauses_session`, `test_afk_workload_shape_resumes_after_crash`.
