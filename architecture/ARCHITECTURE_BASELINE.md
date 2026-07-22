# Architecture Baseline

This document explains the invariants, boundaries, and evidence contract for the Aetheris repository. It does not duplicate dynamic status tables; those are in the marker-generated README section and the JSON ledgers (`architecture/capabilities.json` and `architecture/authority.json`).

## 1. Purpose and proof boundary

The architecture baseline makes current truth executable. It proves, for the checked repository revision:

- every registered major capability has an explicit implementation, measurement, adoption, default, and readiness state;
- each authority-bearing operation is declared;
- every declared side effect is assigned to an existing boundary owner;
- runtime defaults agree with the ledger;
- generated README status content agrees with the ledger;
- direct Python side-effect call sites are either registered or fail CI;
- adoption evidence distinguishes observed values from unknowns;
- no tracked runtime/generated artifacts are committed;
- the governance implementation does not alter runtime authority or behavior.

The word **prove** in v0 is limited to the checked repository revision, supported Python call-site patterns, declared files, and executed CI evidence. It does not imply perfect semantic proof of arbitrary dynamic Python behavior.

## 2. Capability lifecycle definitions

- **implementation**: `absent | partial | complete | deprecated | replaced`
- **measurement**: `unmeasured | measured | stale | unknown`
- **adoption**: `not_applicable | hold | adopted | rejected | retired | unknown`
- **runtime_default.state**: `on | off | not_applicable | unknown`
- **production_readiness**: `not_ready | ready | unknown`
- **evidence.decision**: `not_applicable | pass | hold | reject | unknown | adopted`
- **rollback.kind**: `config_disable | git_revert | tombstone | restore_backup | discard_sandbox | restart_rehydrate | not_applicable | unknown`

Partial components must remain partial. Do not upgrade them to complete because the package exists.

## 3. Authority dimensions

The ten authority dimensions are:

1. read_files
2. write_files
3. execute_commands
4. reach_network
5. modify_plans
6. modify_memory
7. create_skills
8. promote_skills
9. change_config
10. approve_own_proposals

Boundary IDs in this baseline:
- `execution.safety_layer`
- `network_egress.research_perimeter`
- `network_egress.model_provider`
- `persistence.memory_store`
- `persistence.research_journal`
- `persistence.reliability_journal`
- `persistence.understanding_model`
- `persistence.plan_store`
- `persistence.experience_store`
- `persistence.knowledge_store`
- `persistence.lesson_store`
- `persistence.session_learning_journal`
- `sandbox_validation.model_patch`
- `config.change`

Authority levels:

- **none**: cannot perform or request the operation.
- **advisory**: may return data/advice relevant to the operation but cannot request or perform it.
- **delegated**: may produce an ordinary request/plan that another existing owner validates and executes.
- **direct**: directly performs the operation through the named registered boundary.

Every non-`none` entry requires a boundary or an explicit explanation for a pure advisory result.

## 4. Side-effect classes and current owners

1. **execution** — owner: `SafetyLayer`. No new owner permitted.
2. **network_egress** — owner: `NetworkPerimeter`. No new transport or destination permitted.
3. **persistence** — owners: append-only stores, plan sidecars, snapshots, caches, backups.
4. **sandbox_validation** — owner: model-patch sandbox validator/test runner. Must remain isolated from the live tree.

## 5. Ordinary execution path

Every ordinary registered tool action executes through `SafetyLayer`. The Controller routes tasks through `SafetyLayer.run()`, which evaluates ordered rules (deny-wins) and, if allowed, calls `tool.run()`. No tool executes outside this path.

## 6. Network egress path

No byte leaves the machine except through `NetworkPerimeter.fetch()`. ResearchEngine is the only caller. The default transport uses stdlib `urllib` and never attaches auth, cookies, or runs JavaScript. Tests inject a fake transport so the perimeter is exercised hermetically with zero real egress.

LocalProvider and ApiProvider use `requests.post` for model API calls; this is the only other network path and it goes to operator-configured endpoints, not to the allowlisted research perimeter.

## 7. Persistence paths

All persistent writes go through owned stores:

- `MemoryStore` / `JsonlStore` — event journals and append-only logs
- `PlanStore` — plan sidecars
- `ResearchJournal` — research append-only journal
- `SourceReliability` — reliability journal + snapshot
- `RepoUnderstanding` — model + scan journal
- `ExperienceStore` / `KnowledgeStore` / `LearnedKeywordStore` — learning stores
- `SessionOutcomeLearning` — session outcome journal + index

No wildcard persistence. Every writer is bounded and owned.

## 8. Sandbox validation path

Model-assisted patch validation runs in throwaway sandbox copies. `ModelAssistedPatcher` applies diffs in a temp directory, runs allowlisted tests via `subprocess.run`, and discards the sandbox. Even a passing patch is not applied by the validator; it is handed back as `PatchProposal` content for `ReflectionEngine` to own. The live tree is never touched by the validator.

## 9. Advisory versus authoritative components

- **Advisory (read-only)**: ReasoningEngine, RepoUnderstanding, SourceReliability, experience consumption, session outcome learning, skill promotion mining, ReflectionEngine (returns verdicts; executive enacts).
- **Authoritative**: SafetyLayer (execution), NetworkPerimeter (egress), Controller (task routing), Executive (step scheduling), PlanStore (plan persistence), ReflectionEngine (repair verdict insertion), LearningEngine (keyword adoption + skill promotion).

Unattended Supervisor may stop or bound work but gains no authority. Its only powers are `continue-one-gated-step`, `checkpoint`, and `pause/stop`.

## 10. Evidence and adoption contract

Evidence records live under `architecture/evidence/`. Each record contains:

- configuration snapshot
- benchmark command and paths
- raw observed metrics (null when unknown)
- gate verdict, exit code, and artifact reference
- rollback token (identifier/instruction, never a credential)
- limitations

The checker rejects fabricated metrics, placeholder tokens in committed records, and mismatched revisions.

## 11. Rollback taxonomy

- **config_disable**: flip a config default or env override.
- **git_revert**: revert source to a prior commit.
- **tombstone**: append-only retirement (skills, lessons).
- **restore_backup**: restore from a backup snapshot (understanding model).
- **discard_sandbox**: sandbox is throwaway; no live-tree rollback needed.
- **restart_rehydrate**: restart from journal + snapshot (unattended).
- **not_applicable**: no rollback path (frontend shell).
- **unknown**: not yet designated.

## 12. Known unknowns and scanner limitations

- The AST scanner is a tripwire, not a sound whole-program proof. It covers tracked Python roots (`src/`, `scripts/`) and ignores `.git`, virtual environments, caches, and fixtures through exact path rules.
- Dynamic imports, string-based function references, and behavior hidden behind `getattr`/`setattr` may not be visible to the scanner.
- Evidence capture records only metrics that the output actually contains. Missing metrics are `null`, never inferred from comments.
- The checker does not parse human prose if a gate exposes a typed result.

## 13. How CI enforces the baseline

The `architecture-integrity` CI job runs `python scripts/check_architecture_integrity.py --check` independently of lint and tests. It validates schema, references, runtime defaults, README sync, architecture doc sync, AST side-effect tripwire, hidden authority, tracked artifacts, evidence truthfulness, and CI topology.

Existing specialized gates (research, reasoning, hierarchy, reliability, unattended) remain present and run on every push/PR.

## 14. How to update the baseline without widening authority

1. Edit `architecture/capabilities.json` to update a capability's lifecycle state.
2. Edit `architecture/authority.json` to register new boundaries or exceptions.
3. Run `python scripts/check_architecture_integrity.py --render-readme` to regenerate the README table.
4. Run `python scripts/check_architecture_integrity.py --check` to validate.
5. Commit the updated JSON, regenerated README markers, and any new evidence records.
6. Do not add autonomy features, new tools, new model calls, new network paths, new persistence writers, new planner actions, new repair owners, or new promotion paths.
