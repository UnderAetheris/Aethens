# Aetheris Architecture v1.0 (living spec)

# Aetheris Architecture v1.0
_A living technical specification. This is the reference point for every current and future subsystem. When a design question comes up, this document is the tiebreaker; when it goes stale, update it before writing the code that contradicts it._

**Status:** Foundation complete. Controller, Safety Layer, Tool System, Planner, Evaluation Engine, Knowledge & Experience Memory, Learning Engine v0, Deliberative Reasoning (default-on, gated), the Hierarchical Decomposition + Long-Horizon Orchestration layer (default-off, gated), and the Research Engine v0 — the first subsystem to cross the machine boundary, behind its own dedicated `NetworkPerimeter` egress gate (default-off, gated) — are all built, tested, and closed into a working loop.

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

   FOURTH ADVISOR (the only subsystem that crosses the boundary):
            ┌──────────────────────────────────────────────────┐
            │  ResearchEngine  (Query→Search→Fetch→Extract→       │
            │  Validate→Cite→EvidenceBundle)  — immutable data,   │
            │  terminates in evidence, never in execution.        │
            │  Its ONLY egress is through the NetworkPerimeter:   │
            │  allowlist / HTTPS / budgets / robots / MIME / no   │
            │  auth-cookies-JS / dry-run / task-scoped. deny-wins. │
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

**Built today:** Executive Controller (as `Controller`), Planner, Safety Layer, Tool System, Memory (event/knowledge/experience), Evaluation Engine, Learning Engine, Deliberative Reasoning (default-on, gated), the Hierarchical Decomposition + Long-Horizon Orchestration layer (default-off, gated), and the Research Engine v0 — the first and only subsystem to cross the machine boundary, behind its own dedicated `NetworkPerimeter` egress gate (default-off, gated).
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
| NetworkPerimeter | Being the single network-egress choke point; enforcing allowlist/HTTPS/budgets/robots/MIME/no-auth-cookies-JS/dry-run/task-scope | Let any byte leave without passing its rules; become a tool; gain execution authority | Memory (journal), Tool/transport (GET only) |
| Research Engine | Gathering immutable, cited evidence from allowlisted sources behind the perimeter; returning an `EvidenceBundle` | Execute anything; touch safety; mutate plans/memory/skills/config; make a request outside the perimeter; write back to the web | NetworkPerimeter (egress only), Memory (journal), bounded content cache |

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
5. **Research Engine v0** — the deliberate introduction of the network boundary. This is the first capability that reaches outside the machine, shipped _after_ Skills and _only_ with dedicated safety rules (domain allowlists, rate limits, dry-run previews of every fetch, task-scoped, no background browsing). Its `NetworkPerimeter` is the network analogue of the Safety Layer. **v0 is built, default-off, gated PASS** (see §14); widen the allowlist and evidence classes one measured step at a time behind the same gate.
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

## 14. Research Engine v0 — the network boundary, opened safely

**Status (this milestone):** Built, default-off, and **gated PASS** on the offline-vs-research adoption benchmark, including the absolute unsafe-request clause. This is the boundary the entire architecture was sequenced to reach, and reach *safely*: the internet arrives *last*, behind its own dedicated perimeter, because every guardrail that guards it — advisory seams, immutable outputs, measured adoption, structural incapacity to act — was already proven on the prior milestones. The governing principle: **the internet is an advisory substrate, not an execution authority. Information increases; authority does not.**

**Two structural pillars carry that:**
- **Research is *incapable* of acting, not just forbidden.** The `ResearchEngine` holds no tool, no `SafetyLayer` (execution gate), no plan mutator, no memory/skill/config writer, no executive. Its only output is a frozen `EvidenceBundle` whose schema has no field that expresses an action — the same type-level guarantee `Deliberation` and `Lesson` already carry (`test_engine_holds_no_execution_authority`, `test_evidence_schema_cannot_express_an_action`, `test_evidence_is_immutable`). There is simply no code path from evidence to an edit.
- **A single deny-wins egress gate: the `NetworkPerimeter`.** The network analogue of the `SafetyLayer`: no byte leaves except through `NetworkPerimeter.fetch()`. It enforces, *before any egress*, the full rule set — allowlist, HTTPS-only, redirect caps, per-task request/timeout/size/rate budgets, MIME validation, robots, no auth, no cookies, no JS, dry-run, task-scoped sessions, no background crawling — deny-wins, one choke point, no other path out (`test_non_allowlisted_domain_is_denied`, `test_non_https_is_denied`, `test_redirect_off_allowlist_is_denied`, `test_budgets_close_session_when_exceeded`, `test_mime_and_size_limits_enforced`, `test_robots_respected`, `test_no_auth_no_cookies_no_js`, `test_dry_run_emits_zero_egress`, `test_sessions_are_task_scoped_no_background`).

**The pipeline is strictly one-directional and terminates in data:** `Query → Search → Fetch → Extract → Validate → Cite → EvidenceBundle`, and **nothing after that.** No branch loops back into planning or acting, the same shape as the reasoning pipeline that ends in a `Deliberation`. It is honest by construction: `contradictions` and `unknowns` are first-class fields, so "sources disagree" and "couldn't find out" are correct outputs, never smoothed into false certainty (`test_conflicting_sources_recorded_as_contradictions`, `test_absent_evidence_yields_unknowns_not_fabrication`, `test_every_finding_has_full_provenance_and_citation`). Every finding answers where/when/domain/confidence/cached/hash/citation/why-trusted.

**Consumers stay exactly as they've always been; may consult; none required; all can ignore:** Reasoning folds evidence in as `Observation`s but still abstains on thin/contradictory input (`test_reasoning_uses_research_but_still_abstains_on_thin`); Understanding annotates *beside* the repo model and **never rewrites the AST-derived truth** (`test_understanding_annotates_without_mutating_repo_model`); Reflection/Planner still own their decisions and every edit still passes `SafetyLayer.run()` (`test_reflection_owns_verdict_edits_still_gated`); Learning can only get *more* conservative (`test_learning_only_more_conservative_with_research`). Research off is **byte-identical** to Hierarchical v0 (`test_research_off_is_byte_identical_to_hierarchical_v0`).

**The gate (research is the only variable; offline baseline = Hierarchical v0):** `adopt_default_on` iff ALL — `completion` (≥ baseline), `hallucination` (≤ baseline) **and** `citation_correctness` (≥ threshold), `no_regress` (zero), `no_authority_increase` (verified structurally), `zero unsafe_requests`, `network_within_budget`. On the shipped fixtures the run reports: **completion 0.0 → 0.67, hallucination 1.0 → 0.0, citation_correctness 0.0 → 1.0, blocked/unsafe flat at 0, regressions 0, authority increase 0, unsafe requests 0.** All clauses satisfied. And the **unsafe-request clause is absolute**: `test_single_unsafe_request_fails_the_gate` — one off-allowlist attempt and the gate rejects, no matter how good completion looks.

**What did NOT change:** The execution `SafetyLayer`, Tools, Planner authority, Reflection/Understanding/Learning ownership + their measured gates, the reasoning/experience schemas, the retirement policy, the model-patching trust boundary, and the hierarchical orchestrator's compose-never-bypass discipline are all untouched. The Research Engine is a fourth read-only advisor plus a dedicated network-egress perimeter. It adds **no execution path** and **no authority**; its most powerful act is permitting an allowlisted, HTTPS, budgeted byte to leave, and returning immutable evidence about it. With Research off, the system is the proven offline system, byte-identical.

**Status (this milestone — Default-Off, Gated):** `research_enabled` remains `False` by default (mirrors `hierarchy_enabled`). The engine is available (gated PASS on the current fixtures, zero unsafe requests) but **kept default-off** pending a wider workload benchmark and allowlist widening, per the design doc's conservative stance. Flipping default-on is a separate, isolated, reviewable action.

**Next concrete action:** Widen the allowlist and evidence classes one measured step at a time, each behind the same gate; feed research outcomes into Experience (which sources/claims proved reliable) so the loop learns/retires domain trust, bounded and reversible. Let Reasoning + Model-Assisted Patching consult evidence so a patch or plan is grounded in documented behavior, still validated-before-trust, still gated. **Hold the line permanently:** the moment research is asked to *do* rather than *inform*, that is a new subsystem behind its own gate, not an expansion of this one. No autonomous browsing, no auth, no write-back to the web, ever. Better informed, never more powerful.

### Research Engine v0 — wider benchmark + adversarial perimeter hardening (permanent CI guard)

**Status (this milestone):** The narrow gate's *measurement* was widened, not the engine. Research stays default-off and the expanded gate **PASSES** on a realistic workload of **ten hermetic fixture classes** (no live web, content-hashed, deterministic): the six source types real coding tasks hit — `api_docs`, `standards`, `library_ref`, `changelog`, `troubleshooting`, `compatibility` — each carrying a **divergence precondition** (research-off plausibly wrong/hallucinates, research-on correct from a cited fact); plus three **adversarial honesty classes** treated as first-class scored WINS — `stale_source` (prefer fresh, down-weight stale), `contradictory` (record the conflict, lower confidence, don't smooth), `insufficient` (abstain with explicit unknowns); plus `control` (no external fact, byte-identical off vs on). The unit of evaluation is the **consumer's decision**, not the evidence's eloquence: a gorgeous but un-adopted bundle scores zero help.

**Honesty under bad evidence is a measured axis, not a hope.** The benchmark reports `contradiction_handling`, `freshness_discrimination`, and `abstention_correctness` and the expanded gate requires all three ≥ 0.8. A research engine that confidently repeats a stale fact or smooths over a conflict **fails the gate even if completion rose.** On the shipped fixtures the run reports: **completion 0.4 → 1.0, hallucination 0.6 → 0.0, citation_correctness 0.0 → 1.0, research_usefulness 0.6, contradiction_handling 1.0, freshness_discrimination 1.0, abstention_correctness 1.0, regressions 0, authority increase 0, unsafe requests 0.** All clauses satisfied. The **unsafe-request clause stays absolute**: `test_single_unsafe_request_fails_gate` (wide) — one off-allowlist attempt and the gate rejects regardless of completion.

**The NetworkPerimeter hardening suite is adversarial and deny-wins on every rule, with zero real egress** (`tests/test_research_hardening.py`, 18 tests): allowlist denies unknown domain, HTTPS-only denies plaintext, off-allowlist redirect denied, redirect cap enforced, request budget closes the session, timeout budget enforced (slow source leaks zero bytes, never counted unsafe), size limit enforced, MIME validation rejects binary, robots disallow respected, no auth/cookies/JS sent, dry-run emits zero egress, sessions task-scoped with no background thread; plus re-asserted structural incapacity under the wider workload, evidence immutability + no-action-field, and the single-egress-path guarantee. **No perimeter code changed** — these tests prove it cannot be talked around.

**This guard lives in CI permanently, not as a one-run check.** `.github/workflows/ci.yml` now runs three research jobs on every change — `research-gate` (narrow), `research-wide-gate` (the realistic + adversarial benchmark + expanded gate), and `research-hardening` (the perimeter adversarial suite) — each failing the build on regression (including any honesty regression or any weakened perimeter rule). The two new test files also run under the default `pytest` job. A green suite that keeps running is the only guard an open network boundary can afford: a future refactor that quietly weakens a perimeter rule fails the build. The gate itself and the perimeter are untouched — CI = enforcement plumbing only.

**What did NOT change:** The execution `SafetyLayer`, Tools, Planner authority, Reflection/Understanding/Learning ownership + their measured gates, the reasoning/experience/retirement schemas, the Research Engine schema, the `NetworkPerimeter` (still the only egress gate), and the consumers are all untouched. This milestone adds a wider benchmark, the adversarial honesty axes, the perimeter hardening suite, re-asserted structural checks on the wider path, and the expanded gate re-run — all measurement + hardening, no rewrite. Research remains a read-only advisor; with research off or on insufficient/off-allowlist evidence, behavior is byte-identical to Hierarchical v0.

**Next concrete action:** Feed research outcomes into Experience (which domains/claims proved reliable vs stale/contradicted) so the closed loop learns and *retires* domain trust, bounded and reversible — still advisory, still gated. **Hold the §11/§14 line forever:** widen the allowlist and evidence classes one measured step at a time; never add an egress path, never add auth/cookies/JS, never allow autonomous or background browsing, never let research *do* rather than *inform*. Information increases; authority does not. Depth over speed. Never trade a guarantee for a shortcut.

## What to build next
**Immediate: harden Learning Engine v0 into durable, versioned state.** Persist the learned `extra_keywords` to a JSON file the Planner loads on boot, and add `revert_last()` backed by the experience log. This is small, it's the natural continuation of the loop you just closed, and it's the prerequisite for _any_ future widening of what the system can learn, without it, accepted improvements evaporate on restart and there's no audit-grade way to undo a bad one.

**Then: Executive Controller v1 + Task Queue v1**, so the system can hold a backlog and run its own evaluation/learning during idle time instead of on manual trigger. That turns Aetheris from "a loop you run" into "a system that runs itself, safely."

Everything after that (Skills -> Research -> Multi-Agent) layers onto this same spine: **plan -> act safely -> measure -> record -> improve.** Keep that sentence true for every new subsystem and the architecture stays coherent no matter how large it grows.