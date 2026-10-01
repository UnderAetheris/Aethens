# F03: Planner + Hierarchical decomposition

**Status:** `built` (planner, multistep planner, planner-with-model, hierarchy)
**Default:** planner on; hierarchy off (`AETHERIS_HIERARCHY=1`)
**Module:** `src/aetheris/planner/`, `src/aetheris/hierarchy/`

## 1. Purpose
Turn a task into a structured plan; for big goals, into a validated DAG of subgoals executed one gated plan at a time.

## 2. User-facing abilities
- "Build X" -> subgoals, progress, resume, per-branch failure isolation
- Understands long-term goals via hierarchical decomposition

## 3. Current state
`Plan(tool, arg, reason, confident)`; `MultiStepPlan`; `GoalDecomposer` + `GoalOrchestrator` with stable content IDs, subtree retry budgets, subtree rollback, append-only `goal_graph` journal, cancellation. Gate PASS (completion 0.0 -> 1.0, duplicate work 1 -> 0) but kept default-off pending wider workloads.

## 4. Next design steps
- **Wider benchmark:** module + tests + dependents; partially-done goals; skill-covered subgoals; failing-branch isolation
- **Long-term goals store:** owner goals (weeks/months) as root nodes with acceptance criteria encoded as eval cases
- **Model-assisted decomposition** (F13) stays advisory; DAG validation rejects cycles/over-depth before execution

## 5. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| modify_plans | direct | persistence.plan_store |
| execute_commands | none (orchestrator) / delegated via Executive | execution.safety_layer |

## 6. Safety rules
One plan in flight; orchestrator holds no tool/SafetyLayer handle (`test_orchestrator_has_no_tool_or_safety_handle`).

## 7. Adoption gate (hierarchy default-on)
Existing clauses (`larger_completion`, `one_axis_better`, `no_regress`, `safe_neutral`, `no_authority_increase`) across >= 4 workload shapes.

## 8. Rollback
`config_disable` (`AETHERIS_HIERARCHY=0`).

## 9. Tests to add
`test_long_term_goal_persists_and_resumes`, `test_goal_acceptance_criteria_are_eval_cases`.
