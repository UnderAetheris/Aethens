# F02: Controller, Executive, Task Queue

**Status:** Controller + Executive `built`; Task Queue `partial` (`tests/test_task_queue.py` exists; persistence/priority/retry per living spec §9 not yet complete)
**Default:** on
**Module:** `src/aetheris/controller/`

## 1. Purpose
Receive work, route it through Planner -> SafetyLayer -> Tool, record everything, return a result. The Executive steps multi-step plans; the Queue owns *when* and *in what order*.

## 2. User-facing abilities
- Submit a task and get a `TaskResult(ok, output)`
- Queue many tasks with priorities; see their state
- Resume the backlog after restart

## 3. Current state
Controller routes tasks and logs `task_received`, `plan_selected`, `plan_uncertain`, `action_*`, `task_completed|blocked`. Executive runs `MultiStepPlan` steps (`executive.step()` = `run_once()`), used by hierarchy and the unattended supervisor.

## 4. Design: Task Queue v1
- States: `queued -> planning -> executing -> done | blocked | failed | cancelled`
- Ordering: priority (0-3) then FIFO
- Persistence: append-only JSONL journal + snapshot via an owned store (`persistence.task_queue`, new boundary)
- Retries: bounded (default 2) for transient failures only; classified by error type
- Idle hook: when queue empty, Executive v1 may schedule evaluation/learning/curiosity (F07, F08, F16) as low-priority internal tasks

## 5. Inputs / outputs
`enqueue(task: TaskSpec) -> task_id`; `status(task_id) -> TaskState`; `cancel(task_id)`; `next() -> TaskSpec | None`.

## 6. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| execute_commands | delegated | execution.safety_layer |
| modify_plans | direct (queue state only) | persistence.task_queue (new) |
| change_config | none | |
| approve_own_proposals | none | |

## 7. Safety rules
- Controller never calls `tool.run()` directly
- Queue never decides *how* a task runs (Planner owns that)
- Internal (self-scheduled) tasks are tagged `origin=internal` and always lower priority than owner tasks

## 8. Adoption gate
Restart-resume 100% on injected crash; zero duplicate execution; owner-task latency unchanged with idle work enabled.

## 9. Rollback
`config_disable` (queue off -> synchronous single-task path).

## 10. Risks
Queue journal corruption -> snapshot + journal replay with checksum; idle work starving owner tasks -> strict priority.

## 11. Milestones
v1 persistent FIFO+priority -> v1.1 retries -> v1.2 idle scheduling hook.

## 12. Tests
`test_queue_persists_across_restart`, `test_priority_then_fifo`, `test_transient_retry_bounded`, `test_internal_tasks_never_preempt_owner`.
