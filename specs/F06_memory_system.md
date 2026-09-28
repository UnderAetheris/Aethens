# F06: Memory system

**Status:** Event / Knowledge / Experience `built`; user profile + project memory + retrieval ranking `proposed`
**Default:** recording on; experience consumption off
**Module:** `src/aetheris/memory/`

## 1. Purpose
Remember what happened, what is true, what was learned, and who the owner is, in separate stores so signal stays usable.

## 2. Current state
- Event Memory: append-only JSONL firehose
- Knowledge Memory: `KnowledgeEntry(title, source, summary, tags, confidence)`
- Experience Memory: `ExperienceEntry(problem, cause, fix, evidence, related_task, related_eval_case, confidence)` with retirement
- `JsonlStore` is the swap seam
- Experience consumption gated off (`experience_consumption: hold`)

## 3. New stores (proposed)

| Store | Contents | Written by | Read by |
| --- | --- | --- | --- |
| **Profile** | owner preferences (tone, report cadence, working hours, approved roots, AFK allowed hours) | owner only (explicit) | persona, reports, supervisor |
| **Project** | per-project facts, conventions, decisions | owner + Learning (reviewed) | planner, reasoning |
| **Research summaries** | distilled `EvidenceBundle` digests | Research (F15), curiosity (F16) | reasoning |
| **Skill history** | version, gate result, promotion/retirement | F09 | reports |

## 4. Retrieval
- v0: tag + keyword match (deterministic)
- v1: optional embeddings (local small model or ChromaDB) behind the same interface, gated by a retrieval benchmark (precision@5 on held-out lessons)
- Usefulness score = times retrieved and followed by success / times retrieved; low scores decay then tombstone

## 5. Rules
- Every entry: id, created_at, source, version, confidence, links by reference
- Editable = new version appended; old versions kept
- Unverified research never enters Knowledge at high confidence
- Profile is never written by the agent

## 6. Authority
| Dimension | Level | Boundary |
| --- | --- | --- |
| modify_memory | direct (own stores) | persistence.* |
| modify_memory (profile) | none for agent | persistence.profile (owner) |

## 7. Adoption gate (experience consumption / retrieval v1)
Completion >= baseline, repairs <= baseline, zero regressions, retrieval precision@5 >= 0.7.

## 8. Rollback
`tombstone` for entries; `config_disable` for consumption.

## 9. Scale concern
JSONL fine to ~100k events on this laptop; move to SQLite behind `JsonlStore` interface before that.

## 10. Tests
`test_profile_not_writable_by_agent`, `test_memory_edit_appends_version`, `test_low_usefulness_decays_to_tombstone`.
