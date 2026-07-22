"""ChangeSet and RollbackReceipt models — immutable, additive-only accountability records.

No new runtime authority.  No modification to existing writers, journals,
safety boundary, planner, reflection, learning, reasoning, research,
unattended, or trace/replay internals.  These are pure data contracts that
existing subsystems may append through their existing append-only paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..trace.model import Provenance, TraceValue, TraceUnknown


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ChangeKind(str, Enum):
    FILE_EDIT = "file_edit"
    PLAN_EDIT = "plan_edit"
    SKILL_PROMOTION = "skill_promotion"
    SKILL_RETIREMENT = "skill_retirement"
    LEARNING_ADOPTION = "learning_adoption"
    LEARNING_DEMOTION = "learning_demotion"
    SESSION_CHECKPOINT = "session_checkpoint"
    RESEARCH_EVIDENCE_UPDATE = "research_evidence_update"
    CONFIG_TOGGLE = "config_toggle"
    BENCHMARK_ADOPTION = "benchmark_adoption"
    JOURNAL_UPDATE = "journal_update"
    SNAPSHOT_UPDATE = "snapshot_update"
    MODEL_PATCH_PROPOSAL = "model_patch_proposal"
    MODEL_PATCH_VALIDATION = "model_patch_validation"
    EXPERIENCE_RECORD = "experience_record"
    KNOWLEDGE_UPDATE = "knowledge_update"
    UNKNOWN = "unknown"


class RollbackKind(str, Enum):
    GIT_REVERT = "git_revert"
    RESTORE_SNAPSHOT = "restore_snapshot"
    TOMBSTONE_UNRETIRE = "tombstone_unretire"
    CONFIG_DISABLE = "config_disable"
    DISCARD_SANDBOX = "discard_sandbox"
    RESUME_CHECKPOINT = "resume_checkpoint"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# ChangeSet
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChangeSet:
    change_id: str
    trace_id: str | None
    task_id: str | None
    session_id: str | None
    plan_id: str | None
    capability_id: str
    subsystem: str
    change_kind: str
    before_hash: str
    after_hash: str
    before_ref: TraceValue
    after_ref: TraceValue
    inverse_operation: str
    rollback_token: str | None
    revision: TraceValue
    config_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    authority_class: str
    provenance: Provenance
    unknowns: tuple[TraceUnknown, ...]
    created_at: TraceValue


# ---------------------------------------------------------------------------
# RollbackReceipt
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RollbackReceipt:
    receipt_id: str
    change_id: str
    rollback_kind: str
    rollback_target: TraceValue
    rollback_outcome: TraceValue
    confirmed_restored_state: TraceValue
    unknowns: tuple[TraceUnknown, ...]
    provenance: Provenance
    before_hash: str
    after_hash: str
    revision: TraceValue
    config_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    created_at: TraceValue
