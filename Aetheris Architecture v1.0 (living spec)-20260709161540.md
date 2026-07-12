# Aetheris Architecture v1.0 (living spec)

# Aetheris Architecture v1.0
_A living technical specification. This is the reference point for every current and future subsystem. When a design question comes up, this document is the tiebreaker; when it goes stale, update it before writing the code that contradicts it._

**Status:** Foundation complete. Controller, Safety Layer, Tool System, Planner, Evaluation Engine, Knowledge & Experience Memory, Learning Engine v0, Deliberative Reasoning (default-on, gated), and the Hierarchical Decomposition + Long-Horizon Orchestration layer (default-off, gated) are all built, tested, and closed into a working loop.

* * *
## 1\. System vision
### What Aetheris is becoming
Aetheris is a **modular, self-improving agent system** that receives tasks, plans how to accomplish them, executes through a safety-gated tool layer, measures its own performance against benchmarks, and improves itself in small, reversible, provable steps. The long arc: an agent that gets measurably better over time without a human editing its logic for every improvement, and without ever escaping the guardrails that make it trustworthy.
### What it is not
*   **Not a monolithic "one giant brain."** No single model or module holds all the logic. Capability lives in small, replaceable subsystems with clear contracts.
*   **Not an open-ended autonomous agent.** It does not wander the internet, rewrite itself freely, or take unbounded action. Every capability is introduced deliberately, behind the safety gate.
*   **Not an LLM wrapper.** The core loop is deterministic and testable today. LLM-based components (planner, evaluation) are a _future upgrade path_ layered onto a measurable baseline, not the foundation.
### Core design philosophy
1. **Modularity over cleverness.** Every subsystem is swappable behind an interface. A better planner or a real database drops in without touching the rest.
2. **Safety is structural, not procedural.** No tool runs except through one choke point. This is a property of the code shape, not a rule people remember to follow.
3. **Measure before you improve.** Nothing is "better" without a benchmark saying so. The evaluator is the arbiter of every change.
4. **Bounded, reversible change.** The system may improve itself, but only one small step at a time, and only in ways it can cleanly undo.
5. **Determinism first.** Build the deterministic version, prove it with tests, then consider adding intelligence on top. A stable baseline is what makes "did this help?" answerable.

* * *
## 2\. Subsystem map

```plain
                        ┌─────────────────────────────┐
                        │     Executive Controller     │  (v0: Controller; v1: adds queue + policy)
                        └──────────────┬──────────────┘
                                       │
                   ┌─────────────────────┼─────────────────────┐
                  ▼                     ▼                     ▼
            ┌──────────┐         ┌─────────────┐        ┌──────────────┐
            │ Planner  │────────▶│ Safety Layer │───────▶│  Tool System │
            └────┬─────┘  plan   └──────┬──────┘ action └──────┬───────┘
                 │                       │                      │
                 │                       ▼                      │
                 │                 ┌───────────┐                │
                 └────────────────▶  Memory   ◀────────────────┘
                                  │ (events)  │
                                  └───────────┘

   ADVISORY LAYER (above the planner, composes never bypasses):
            ┌──────────────────────────────────────────────────┐
            │  GoalDecomposer (advisory DAG)  ──▶  GoalOrchestrator │
            │  schedules ready leaves ONE-AT-A-TIME to the EXISTING  │
            │  Planner + Executive + Safety Layer spine.             │
            │  Holds no tool, no SafetyLayer, no writer.             │
            └──────────────────────────────────────────────────┘
                                 └─────┬─────┘
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            ┌──────────────┐   ┌───────────────┐   ┌───────────────┐
            │  Knowledge   │   │  Experience   │   │  Evaluation   │
            │   Memory     │   │    Memory     │   │    Engine     │
            └──────────────┘   └───────┬───────┘   └───────┬───────┘
                                       │                   │
                                       ▼                   ▼
                                 ┌───────────────────────────┐
                                 │      Learning Engine       │
                                 └───────────────────────────┘
                        (reads eval + experience, proposes bounded fixes)

   FUTURE:  Research Engine  ·  Skill System  ·  Multi-Agent Layer  (all behind the same gate)
```

**Built today:** Executive Controller (as `Controller`), Planner, Safety Layer, Tool System, Memory (event/knowledge/experience), Evaluation Engine, Learning Engine, Deliberative Reasoning (default-on, gated), and the Hierarchical Decomposition + Long-Horizon Orchestration layer (default-off, gated).
**Planned:** Task Queue, Research Engine, Skill System, Multi-Agent Layer, Executive Controller v1.

* * *
## 3\. Responsibilities

| Subsystem | Owns | Must never | Depends on |
| ---| ---| ---| --- |
| Executive Controller | Receiving a task, orchestrating the plan -> safety -> tool -> log flow, returning a result | Execute a tool directly; make safety decisions; choose tools itself | Planner, Safety Layer, Tool Registry, Memory |
| Task Queue (future) | Ordering, persisting, and scheduling pending work; retries; long-running task state | Decide how a task is done (that's Planner) | Controller, Memory |
| Planner | Turning a task into a structured `Plan(tool, arg, reason, confident)` | Execute anything; touch safety; guess when unsure (must fall back) | Nothing (pure function over task + learned keywords) |
| Safety Layer | Being the single execution gate; evaluating rules; enforcing safe\_mode; logging every attempt; dry-run + reversibility seam | Let any action run without passing its rules | Memory (for logging), Tool metadata (`safe` flag) |
| Tool System | Defining tools + registry; actually performing side effects; exposing `safe` flag and `undo` hooks | Run outside the Safety Layer; hide side effects | Nothing (tools are leaf capabilities) |
| Event Memory | Append-only log of everything that happened | Curate, dedupe, or interpret (it's a firehose) | Nothing |
| Knowledge Memory | Durable facts, doc summaries, learned patterns | Store raw events; hold unvalidated speculation as high-confidence | Nothing (fed by Learning + humans) |
| Experience Memory | Problem/cause/fix lessons linked to tasks + eval cases | Store facts (that's Knowledge) | Nothing (fed by Learning) |
| Evaluation Engine | Running benchmark cases end-to-end; scoring tool choice + output; producing a pass rate | Modify the system it measures; use fuzzy/LLM grading (v0) | Controller, Planner, Memory |
| Learning Engine | Detecting failures, proposing ONE bounded reversible change, testing it, accepting/rolling back | Rewrite source; batch changes; touch tools/safety; act without an eval verdict | Evaluator, Knowledge, Experience, Planner's `extra_keywords` |
| Research Engine (future) | Gathering external information through the network boundary | Bypass Safety; act autonomously without task scope | Safety Layer, Tool System, Memory |
| Skill System (future) | Composing tools into higher-level reusable multi-step procedures | Bypass Safety; embed tool logic it doesn't own | Planner, Tool System, Safety, Evaluator |
| Multi-Agent Layer (future) | Coordinating multiple Aetheris instances/roles | Create an unbounded agent that escapes any single agent's guardrails | Controller, Safety, Memory |

* * *
## 4\. Data flow
**Happy path (one task, today):**

```plain
User task
   │
   ▼
[Controller] ── logs "task_received" ─────────────────────────▶ Event Memory
   │
   ▼
[Planner] returns Plan(tool, arg, reason, confident)
   │
   ├── Controller logs "plan_selected" ──────────────────────▶ Event Memory
   └── if not confident: logs "plan_uncertain" ──────────────▶ Event Memory
   │
   ▼
[Safety Layer].run(tool, request)
   │  evaluates rules (safe_mode gate, path scoping, shell allowlist)
   ├── allowed + executed:  logs "action_allowed" ───────────▶ Event Memory
   ├── blocked:             logs "action_blocked" ───────────▶ Event Memory
   └── dry_run:             logs "action_preview" ───────────▶ Event Memory
   │
   ▼ (only if allowed)
[Tool] performs the action, returns output
   │
   ▼
[Controller] ── logs "task_completed" or "task_blocked" ──────▶ Event Memory
   │
   ▼
TaskResult(ok, output) ──▶ User
```

**Improvement path (offline / idle, today):**

```plain
[Evaluation Engine] runs benchmark suite
   └── logs "eval_case" (per case) + "eval_summary" (pass rate) ──▶ Event Memory
   │
   ▼
[Learning Engine] reads failures
   ├── writes ExperienceEntry (problem/cause/fix, linked to eval case) ──▶ Experience Memory
   ├── proposes ONE Candidate keyword, logs "learning_attempt" ─────────▶ Event Memory
   ├── re-runs Evaluator with the trial change
   │
   ├── accepted (strictly better, no regressions):
   │     ├── commits change to Planner.extra_keywords (reversible state)
   │     ├── writes KnowledgeEntry (the learned rule) ──────────────────▶ Knowledge Memory
   │     └── logs "learning_accepted" ─────────────────────────────────▶ Event Memory
   │
   └── rejected (worse / inconclusive / regression):
         └── discards trial, logs "learning_rejected" ─────────────────▶ Event Memory
```

**Where records are written:**
*   **Event Memory** — every step of both paths (audit firehose).
*   **Experience Memory** — on each detected failure, by the Learning Engine.
*   **Knowledge Memory** — on each accepted improvement (and by humans, deliberately).

**Feedback loops:** (1) Tool result -> Event Memory -> Evaluator score. (2) Evaluator failures -> Experience Memory -> Learning candidate -> Evaluator re-run -> accept/rollback. Loop (2) is the self-improvement engine; it only ever runs offline against the benchmark, never against live user tasks.

* * *
## 5\. Execution lifecycle
**When a user sends a task:** Controller logs receipt, asks the Planner for a `Plan`, logs the plan (and any uncertainty), builds an `ActionRequest`, and hands it to the Safety Layer. The Controller never executes; it orchestrates.

**During tool execution:** The Safety Layer is the only path to `tool.run()`. It evaluates its rule pipeline (deny-wins): the `safe_mode` gate blocks unsafe tools wholesale; `path_within_root` blocks filesystem escapes; `shell_allowlist` blocks non-whitelisted commands, both enforced even when safe\_mode is off. If `dry_run` is set, it previews without executing. Every outcome is logged. Only an allowed, non-dry-run action reaches the tool.

**During evaluation:** The Evaluator runs each benchmark case through a real, hermetic Controller (temp workspace, own log), captures the planned tool via a recording shim, checks tool choice and (when specified) exact output, and writes per-case + summary records with a pass rate.

**During learning:** The Learning Engine establishes a baseline pass rate, records failures as experience, proposes exactly one keyword candidate, re-runs the Evaluator with that trial change, and commits it only on strict improvement with zero regressions. Otherwise it rolls back. The only thing it mutates is the Planner's `extra_keywords` state.

**When idle:** This is when the improvement path runs. Evaluation and learning are deliberately _offline_ activities. v0 triggers them manually; Executive Controller v1 will schedule them during idle windows so live task latency is never affected by self-improvement work.

* * *
## 6\. Memory model
Three stores, deliberately separate. Conflating them is the classic mistake; keeping them apart is what makes the signal usable.

| Store | Shape | Purpose | Written by | Read by |
| ---| ---| ---| ---| --- |
| Event Memory | Append-only JSONL, one line per event | Raw audit trail of everything that happened | Everyone | Evaluator, Learning Engine, humans debugging |
| Knowledge Memory | `KnowledgeEntry` (title, source, summary, tags, confidence) | Durable, reusable facts and learned patterns | Learning Engine (accepted fixes), humans | Planner (future), humans |
| Experience Memory | `ExperienceEntry` (problem, cause, fix, evidence, related\_task, related\_eval\_case, confidence) | Lessons from real failures, linked to their source | Learning Engine | Learning Engine, humans |

**How they stay separate:** Event is a firehose (noise, never curated). Knowledge and Experience are _curated_ distillations, written only by deliberate processes, and linked to events/tasks/cases **by reference** (string ids), never by copying. The rule of thumb: if it's "what happened," it's an event; if it's "a true thing worth reusing," it's knowledge; if it's "a lesson from something that broke," it's experience.

**Trade-off:** All three are file-based JSONL today. This is intentional (deterministic, hermetic, zero-dependency) but won't scale to large histories or concurrent writers. The `JsonlStore` engine is the seam: swap it for a real database behind the same interface when volume demands, without changing any caller.

* * *
## 7\. Learning model
**What it may change:** Exactly one thing, the Planner's `extra_keywords` map (`intent -> [keyword]`). One keyword per accepted attempt.

**What it may never change:** Source code, tool definitions, safety rules, the evaluator itself, or anything outside its single lever. It cannot batch changes, cannot rewrite logic, cannot disable safety.

**How reversibility works:** The lever is in-memory (soon on-disk) _state_, not source. Applying a change appends a keyword; rolling back drops it. The engine builds a _trial_ rule set and never mutates the live one until a change is proven, so rollback is the default and commit is the exception.

**How improvement is measured:** The Evaluator's pass rate. A candidate is accepted **only if** `new_rate > baseline_rate` **and** no previously-passing case now fails. "Same rate" and "regression" both mean reject.

**How rollbacks work:** Because the live state is never touched during a trial, a rejected candidate requires no undo, the trial is simply discarded and a `learning_rejected` event is logged. For _accepted_ changes that later prove bad, the roadmap's persisted rule set + `revert_last()` will pop the most recent keyword using the experience log.

**Trade-off:** The search space (one keyword mapping) is deliberately tiny, so the engine is safe and testable but only solves a narrow class of planner misses. That's the correct v0 scope: prove the _loop_ works before widening what it can change.

* * *
## 8\. Safety model
**Why Safety is a hard gate:** Trust is the whole product. If any code path can run a tool without passing safety, the guarantee is worthless. So safety is enforced by _shape_: the Controller has no reference to `tool.run()` except through `SafetyLayer.run()`. Bypassing it would require editing the Controller, which the system itself is never allowed to do.

**What can and cannot bypass it:** Nothing bypasses it. Every current and future subsystem (Planner-driven tasks, Skills, Research, Multi-Agent) routes tool execution through the same gate. New capability = new _tools_ and new _rules_, never a new execution path.

**How safe\_mode works:** A config flag (`AETHERIS_SAFE_MODE`, default on). With it on, any tool not explicitly `safe=True` is blocked outright, read/list/echo work, write/shell are denied. With it off, unsafe tools become _eligible_ but still face the fine-grained rules (`path_within_root`, `shell_allowlist`). safe\_mode is the coarse switch; the rules are the always-on fine-grained layer.

**How undo/rollback fits in:** Tools may declare an `undo` hook (e.g. `write_file` snapshots to a `.aetheris.bak` sidecar and can restore or delete). Dry-run lets any action be previewed without executing. Together these are the reversibility seam: the system can look before it leaps, and step back after. Not every action is reversible (shell honestly declares no undo), and admitting that is safer than faking it.

**Rule pipeline (deny-wins):** Rules are an ordered list of callables; the first veto stops execution; if none veto, the action runs. Adding a guardrail is appending a rule, never a core rewrite.

* * *
## 9\. Task and project management
**How tasks should be queued (Task Queue v1):** Today the Controller handles one task synchronously. The Queue will own pending work: FIFO with priority override, persisted so a restart doesn't lose the backlog, with per-task state (`queued -> planning -> executing -> done/blocked/failed`) and bounded retries for transient failures. The Queue decides _when_ and _in what order_; the Planner still decides _how_.

**How projects and milestones fit in:** A project is a named collection of tasks with an ordering and acceptance criteria, exactly the shape Aetheris itself was built in (Scaffold -> Safety -> Tools -> Planner -> Eval -> Memory -> Learning). Milestones map to benchmark expansions: each milestone should add eval cases that encode its acceptance criteria, so "done" is measurable, not asserted.

**How long-running work should be tracked:** Via Event Memory as the durable trail plus the Queue's per-task state. A long task checkpoints progress as events so it can be resumed or audited. Nothing important lives only in process memory.

* * *
## 10\. Future roadmap
In recommended order:

1. **Harden Learning v0** — persist `extra_keywords` to disk (survives restarts), add `revert_last()` for durable, auditable version control of learned rules. _Do this before widening what learning can touch._
2. **Executive Controller v1** — promote the Controller from single-task handler to orchestrator: owns the Task Queue, schedules idle-time evaluation + learning, applies policy (when to plan vs defer, when to run the improvement loop).
3. **Task Queue v1** — persistent, prioritized, resumable work queue with per-task lifecycle state and retries.
4. **Skill System v1** — compose tools into higher-level reusable multi-step procedures the Planner can select; scored by the same Evaluator, improved by the same Learning loop. Skills are just "tools made of tools," so they route through Safety unchanged.
5. **Research Engine v1** — the deliberate introduction of the network boundary. This is the first capability that reaches outside the machine, so it ships _after_ Skills and _only_ with dedicated safety rules (domain allowlists, rate limits, dry-run previews of every fetch). This is exactly the boundary the Safety Layer was designed to guard.
6. **Multi-Agent System v1** — multiple coordinated Aetheris roles/instances, each individually gated. Coordination adds a layer; it never creates an ungated super-agent.
7. **Self-maintenance / autonomous improvement (later)** — widen the Learning Engine's levers (beyond planner keywords) _only_ once persistence, versioning, and a much larger benchmark make regressions catchable and reversible at scale.

* * *
## 11\. Explicit non-goals
*   **No uncontrolled self-modification.** The system changes exactly one bounded, reversible lever at a time, gated by measured improvement. It never edits its own source.
*   **No freeform autonomous internet wandering.** Network access arrives only as the Research Engine, task-scoped, and behind dedicated safety rules. No background browsing, no unbounded crawling.
*   **No replacing or weakening the Safety Layer.** Safety is the one component the system may never route around, disable, or rewrite. New capability adds tools and rules; it never adds bypasses.
*   **No monolithic "one giant brain."** Capability stays distributed across small, replaceable subsystems with explicit contracts. No single module accumulates all the logic.

* * *
## 12. Deliberative Reasoning — Decision Amplification v0

**Status (this milestone):** The 5-clause default-on gate now **PASSES** on its own merits. The prior milestone returned an honest `off-but-available` verdict because its fixtures couldn't separate a good advisor from a silent one (code-repair passed identically with reasoning off/on: 0 retries, 0 repairs, 1.0 completion — no decision for reasoning to change). This milestone fixes the *measurement*, not the engine.

**Single design principle:** *A case only counts if the owner can measurably get it wrong without reasoning.* Every non-control, non-thin decision case carries a **divergence precondition**: with reasoning off the owner picks the worse branch (and it shows in the metrics), with reasoning on it picks the better one. A case that produces identical outcomes in both modes is a no-op and is rejected loudly by the harness (`ReasoningComparison.run` raises if any `divergence_required` case fails the precondition), so the benchmark can't quietly refill with no-ops.

**How divergence is produced (no engine change, no new authority):** The benchmark models each owner's *existing* decision surface in `src/aetheris/reasoning/owner_sim.py`, the only module that touches read-only handles (`RepoUnderstanding` query surface, `ReasoningEngine`). Reasoning gains no authority — it only supplies a fact the owner's existing logic already consumes:

*   **Planner** (`skill_vs_decompose`) — reasoning surfaces whether a skill's assumed symbol actually exists (`RepoUnderstanding.defines`) and whether a skill really matches the task (`SkillTemplate.matches`). Without the fact the owner blindly reuses a trap skill / over-decomposes; with it the owner uses its existing skill-or-decompose fallback correctly.
*   **Reflection** (`safer_repair`) — reasoning surfaces the correct exporting module (`exporting_module`, the exact fact Reflection's own repair path consumes) and the existing helper to reuse (`find_helper`). The *tempting* fix is the risky broad-import; the safer fix reuses a helper. Blocked/unsafe attempts stay flat (safety-neutral, stressed).
*   **Learning** (`overfit_adoption`) — reasoning surfaces gain-concentration + repair-cost rise (the `hidden_overfit` case) and a latent safety nudge (the `safety_creep_candidate` case): signals the measured adoption gate cannot see. Reasoning can only make Learning **more** conservative (hold), never force-adopt a gate-failing candidate.

Fixtures are fixed in-repo (`DecisionCase.setup`), hermetic, and deterministic; off/on are reproducible bit-for-bit, so every gate delta is attributable to reasoning and nothing else. Abstention precision/recall are measured on the real engine (≥ 0.8 required) over thin-vs-rich inputs.

**The gate (identical to the prior milestone, not weakened):** `adopt_default_on` iff ALL five — `helps` (completion ≥ baseline, retries/repairs ≤, ≥ 1 decision axis strictly improves), `no_regress` (zero regressions), `safe_neutral` (blocked/unsafe not increased), `abstention_ok` (precision & recall ≥ 0.8), `useful` (`reasoning_usefulness > 0`). The amplified run reports: completion 0.80 → 1.00, retries 7 → 0, repairs 5 → 0, planning/repair/promotion quality 0.00 → 1.00, blocked_unsafe flat at 0, abstention 1.0/1.0. All five clauses satisfied.

**What did NOT change:** SafetyLayer, Tools, Planner authority, Reflection/Understanding/Learning ownership, the reasoning schema, the 5-clause gate, and the hardening suite (313 → 338 green, still green) are all untouched. Reasoning remains read-only, advisory, immutable, structurally incapable of expressing or reaching an action. The comparison harness still has zero execution authority. With reasoning off, the system is byte-identical to before.

**Where reasoning helps / abstains (measured):**
*   Planner: steers away from a skill whose template assumes a missing symbol (`skill_is_a_trap`); recognizes a real skill match under novel surface (`decompose_is_wasteful`).
*   Reflection: prefers helper-reuse over a broad dependents-disturbing import (`tempting_bold_fix`, first-attempt success, flat unsafe); surfaces the correct exporting module so the import is right the first time (`wrong_module_guess`).
*   Learning: holds a candidate whose gain is concentrated in one fixture and raises repair cost elsewhere (`hidden_overfit`); holds a candidate with a safety nudge (`safety_creep_candidate`). Both lower false-adopt rate.
*   Abstains on thin evidence; inert (byte-identical) on control.

**Status (this milestone — Default-On Hardening v1): DONE.** `Config.reasoning_enabled` now defaults to `True`; the flip is earned by the passing gate, not assumed. The only production delta is the resolved default — the seams, engine, schema, and owners' decision surfaces are unchanged; reasoning just runs by default.

**Opt-out is a true rollback.** `resolve_reasoning_enabled(config, env)` gives explicit precedence: `AETHERIS_REASONING=off|0|false` forces the off-path (constructs `reasoning=None`, byte-identical to Repository Understanding v0); `on|1|true` forces on; unset/malformed defers to `config.reasoning_enabled` (never silently forces on). Disabling returns the system to exactly the prior default with no residual half-on state.

**The benchmark is now a CI regression guard.** `.github/workflows/ci.yml` runs `scripts/run_reasoning_gate.py` on every change; it runs the amplified benchmark + the unchanged 5-clause gate and fails the build if `adopt_default_on` is False (any regression: completion drop, retries/repairs rise, a decision axis falls, abstention < 0.8, usefulness ≤ 0, or blocked/unsafe increase). The gate itself is untouched — CI = enforcement plumbing only. Determinism (hermetic, pinned, per-run temp workspace) means a failure is a real regression, never flake. Default-on is continuously re-proven, not assumed.

**Guarantees re-asserted on the live default-on path** (`tests/test_reasoning_default_on.py`): the off-path is byte-identical, env opt-out forces off, malformed env never forces on, the schema still can't express an action, the engine still has no authority, deliberations are immutable, abstention stays first-class, owners keep ownership, safety is flat on the shipping default, and the CI gate still passes. The hardening suite stays green.

**Observability is read-only and unchanged in shape:** `GET /reasoning/status` now reports the live `enabled`/`mode: default-on`/`env_override`; `GET /reasoning/history` is the append-only structured journal. No endpoint toggles, mutates, or triggers anything — a window, never a lever.

**Next concrete action:** Merge the flip as its own tiny, isolated, reviewable commit (config default + env resolver + CI wiring + re-asserted hardening), then let the CI gate ride along on unrelated PRs for a while before layering model enrichment or Coding Skills on top. Confidence in default-on comes from watching the guard hold across real changes, not from one green run. Then continue the roadmap (model enrichment re-gated → Coding Skills → Research Engine last, behind its own safety rules). Never trade a guarantee for a shortcut.

## 13. Hierarchical Decomposition & Long-Horizon Execution v0

**Status (this milestone):** Built, default-off, and **gated PASS** on the flat-vs-hierarchical adoption benchmark. This is not a new planner — it is a *planner that plans plans*. The decomposition layer is a **scheduler over advisory structure**, not an actor: it holds no tool, no `SafetyLayer`, no live writer. It calls the **existing** planner per subgoal and hands ordinary `MultiStepPlan`s to the **existing** Executive, which runs them through the **unchanged** `Planner → Executive → SafetyLayer → Tool` spine. Every executable step is byte-identical to today's.

**Single design principle:** *One gated plan at a time, deterministic order, no concurrency.* Long-horizon reach comes from *many sequential validated plans plus checkpoints*, not from parallel agents. There is no background thread and no hidden execution. That is the whole trick: hundreds of steps are safe because, at every instant, exactly one gated plan is in flight on the proven spine. `test_one_plan_runs_at_a_time_via_existing_executive` is the structural proof; `test_orchestrator_has_no_tool_or_safety_handle` is the canary that the layer never grew an execution surface.

**How the parts compose (grant authority to none):**
- **DAG-validated pre-execution** — a cyclic or over-deep decomposition is rejected/flattened *before* anything runs, so no cycle or deadlock ever reaches the scheduler (`test_decomposition_is_a_validated_dag`, `test_cyclic_decomposition_is_rejected`).
- **Stable content-derived subgoal IDs** — same subgoal shape → same ID, which powers dedup + resume for free (a completed ID never re-runs) (`test_subgoal_ids_are_stable_and_dedup`).
- **Deterministic, one-at-a-time scheduling** — ready = all deps `done`; among ready, topological + stable-ID order; exactly one plan through the existing Executive (`test_scheduling_is_deterministic_topological`, `test_one_plan_runs_at_a_time_via_existing_executive`).
- **Subtree-local retry budget + subtree rollback** — a failing branch retries within its own bounded budget (Reflection owns the repair inside the plan) or blocks only its dependents; independent branches keep going; a subtree reverts via the tool `undo` seam without touching siblings (`test_failed_branch_does_not_restart_independent_branches`, `test_subtree_retry_budget_is_bounded`, `test_dependents_block_when_dependency_fails`, `test_subtree_rollback_leaves_siblings_intact`).
- **Automatic done-detection + dedup + skill reuse** — Understanding facts + the journal show already-satisfied work, which is marked `done` without re-execution; promoted skills are reused via the existing repo-aware selection (`test_already_satisfied_subgoal_is_not_reexecuted`, `test_promoted_skill_is_reused_for_matching_subgoal`).
- **Append-only `goal_graph` journal + snapshot** — every transition is appended; resume reloads the snapshot and replays the tail to the exact frontier; the run is fully reconstructable (`test_resume_skips_completed_subtrees`, `test_journal_is_append_only_and_reconstructs_run`).
- **Cancellation as a journaled state transition** — never a mid-write kill; propagates to un-started descendants (`test_cancellation_propagates_without_midwrite_kill`).
- **Reflection still owns repair** inside each plan; **Learning still owns promotion**; **SafetyLayer still gates every tool**; **Understanding/Experience/Reasoning stay read-only advisors** to *how the graph is shaped*, never to *what executes* (`test_reflection_still_owns_repair_inside_subgoal`).

**The gate (hierarchy is the only variable; flat baseline = Model-Assisted Patching v0):** `adopt_default_on` iff ALL — `larger_completion` (hierarchy completion ≥ flat), `one_axis_better` (retries/repairs/duplicate_work/latency strictly improves on ≥1), `no_regress` (zero regressions), `safe_neutral` (blocked/unsafe not increased), `no_authority_increase` (orchestrator holds no tool/safety handle). On the shipped fixtures the run reports: **completion 0.0 → 1.0, duplicate_work 1 → 0, latency 2 → 4 (more bounded plans, fewer wasted re-runs), blocked/unsafe flat at 0, regressions 0, authority increase 0.** All clauses satisfied. Hierarchy off, or an abstaining/flat decomposer, is **byte-identical** to Model-Assisted Patching v0 (`test_hierarchy_off_is_byte_identical_to_model_patching_v0`, `test_flat_friendly_goal_is_byte_identical`, `test_decomposer_abstains_falls_back_to_flat`).

**What did NOT change:** SafetyLayer, Tools, Planner authority (the *same* planner is called per subgoal), Reflection ownership, Understanding/Learning ownership + their measured gates, the reasoning schema, the experience schema, the retirement policy, and the model-patching trust boundary are all untouched. The decomposition layer composes them: it proposes an advisory DAG, schedules ready leaves one at a time to the existing Executive, checkpoints transitions, and merges completed branches by resolving dependency edges. It adds **no execution path, no background agent, no authority.** The closed-loop subsystems (Reflection, Learning, Experience) are unchanged and still own repair, promotion, and memory respectively.

**Status (this milestone — Default-Off, Gated):** `run_goal(hierarchy=False)` remains the default and is byte-identical to the prior milestone. The layer is available (gated PASS on the current fixtures) but **kept default-off** pending broader multi-plan workload benchmarking, per the design doc's conservative stance. Flipping default-on is a separate, isolated, reviewable action to take only after the gate holds across more workloads.

**Next concrete action:** Benchmark flat-vs-hierarchical on a wider set of multi-plan workloads (module + tests + dependents; partially-done goals; skill-covered subgoals; failing-branch isolation). Flip default-on *only* if the outcome axes continue to clear the gate with zero regressions, flat safety, and zero authority increase. Then the **Research Engine is genuinely the next step** — still behind its own dedicated rules (domain allowlists, rate limits, dry-run previews, task-scoped, never background browsing). Hold the order through this one too: prove bounded orchestration before the network boundary.

## What to build next
**Immediate: harden Learning Engine v0 into durable, versioned state.** Persist the learned `extra_keywords` to a JSON file the Planner loads on boot, and add `revert_last()` backed by the experience log. This is small, it's the natural continuation of the loop you just closed, and it's the prerequisite for _any_ future widening of what the system can learn, without it, accepted improvements evaporate on restart and there's no audit-grade way to undo a bad one.

**Then: Executive Controller v1 + Task Queue v1**, so the system can hold a backlog and run its own evaluation/learning during idle time instead of on manual trigger. That turns Aetheris from "a loop you run" into "a system that runs itself, safely."

Everything after that (Skills -> Research -> Multi-Agent) layers onto this same spine: **plan -> act safely -> measure -> record -> improve.** Keep that sentence true for every new subsystem and the architecture stays coherent no matter how large it grows.