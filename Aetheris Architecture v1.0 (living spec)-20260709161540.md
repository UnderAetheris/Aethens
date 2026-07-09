# Aetheris Architecture v1.0 (living spec)

# Aetheris Architecture v1.0
_A living technical specification. This is the reference point for every current and future subsystem. When a design question comes up, this document is the tiebreaker; when it goes stale, update it before writing the code that contradicts it._

**Status:** Foundation complete. Controller, Safety Layer, Tool System, Planner, Evaluation Engine, Knowledge & Experience Memory, and Learning Engine v0 are all built, tested, and closed into a working loop.

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

**Built today:** Executive Controller (as `Controller`), Planner, Safety Layer, Tool System, Memory (event/knowledge/experience), Evaluation Engine, Learning Engine.
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
## What to build next
**Immediate: harden Learning Engine v0 into durable, versioned state.** Persist the learned `extra_keywords` to a JSON file the Planner loads on boot, and add `revert_last()` backed by the experience log. This is small, it's the natural continuation of the loop you just closed, and it's the prerequisite for _any_ future widening of what the system can learn, without it, accepted improvements evaporate on restart and there's no audit-grade way to undo a bad one.

**Then: Executive Controller v1 + Task Queue v1**, so the system can hold a backlog and run its own evaluation/learning during idle time instead of on manual trigger. That turns Aetheris from "a loop you run" into "a system that runs itself, safely."

Everything after that (Skills -> Research -> Multi-Agent) layers onto this same spine: **plan -> act safely -> measure -> record -> improve.** Keep that sentence true for every new subsystem and the architecture stays coherent no matter how large it grows.