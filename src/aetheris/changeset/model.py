"""ChangeSet and RollbackReceipt models — immutable, additive-only accountability records.

No new runtime authority.  No modification to existing writers, journals,
safety boundary, planner, reflection, learning, reasoning, research,
unattended, or trace/replay internals.  These are pure data contracts that
existing subsystems may append through their existing append-only paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from ..trace.model import Provenance, TraceUnknown, TraceValue


class ChangeKind(str, Enum):
    FILE_EDIT = "file_edit"
    PLAN_EDIT = "plan_edit"
    SKILL_PROMOTION = "skill_promotion"
    SKILL_RETIREMENT = "skill_retirement"
    LEARNING_ADOPTION = "learning_adoption"
    LEARNING_DEMOTION = "learning_demotion"
    SESSION_CHECKPOINT = "session_checkpoint"
    RESEARCH_EVIDENCE_APPEND = "research_evidence_append"
    CONFIG_TOGGLE = "config_toggle"
    BENCHMARK_ADOPTION = "benchmark_adoption"
    JOURNAL_APPEND = "journal_append"
    SNAPSHOT_UPDATE = "snapshot_update"
    MODEL_PATCH_PROPOSAL = "model_patch_proposal"
    MODEL_PATCH_VALIDATION = "model_patch_validation"
    EXPERIENCE_APPEND = "experience_append"
    KNOWLEDGE_APPEND = "knowledge_append"
    UNKNOWN = "unknown"


class MutationDisposition(str, Enum):
    REVERSIBLE = "reversible"
    COMPENSATABLE = "compensatable"
    APPEND_ONLY = "append_only"
    REBUILDABLE_SNAPSHOT = "rebuildable_snapshot"
    EPHEMERAL = "ephemeral"
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


class RollbackOutcome(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ObjectIdentity:
    object_type: str
    scope: str
    locator: TraceValue
    hash_algorithm: Literal["sha256", "not_applicable", "unknown"]
    digest: TraceValue
    size_bytes: TraceValue
    version_ref: TraceValue

    def __post_init__(self) -> None:
        if self.hash_algorithm == "sha256":
            alg_digest = self.digest
            if alg_digest.state == "known" and alg_digest.value is not None:
                d = str(alg_digest.value)
                if not (len(d) == 64 and all(c in "0123456789abcdef" for c in d)):
                    raise ValueError(
                        f"sha256 digest must be exactly 64 lowercase hex characters: {d!r}"
                    )


@dataclass(frozen=True)
class InverseReference:
    kind: RollbackKind
    owner_subsystem: str
    authority_boundary: str | None
    target: TraceValue
    preconditions: tuple[str, ...]
    expected_restore_identity: ObjectIdentity | None
    authorization_required: TraceValue
    executable: Literal[False] = False

    def __post_init__(self) -> None:
        if self.executable is not False:
            raise ValueError("inverse reference executable must be False")


@dataclass(frozen=True)
class RestorationConfirmation:
    status: Literal[
        "confirmed",
        "partially_confirmed",
        "not_confirmed",
        "not_applicable",
        "unknown",
    ]
    expected: ObjectIdentity | None
    observed: ObjectIdentity | None
    verifier: TraceValue
    compared_fields: tuple[str, ...]
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class ChangeSet:
    schema_version: int
    change_id: str
    trace_id: TraceValue
    task_id: TraceValue
    session_id: TraceValue
    plan_id: TraceValue
    capability_id: str
    owner_subsystem: str
    change_kind: ChangeKind
    disposition: MutationDisposition
    authority_class: str
    target: ObjectIdentity
    before: ObjectIdentity
    after: ObjectIdentity
    inverse: InverseReference
    rollback_ref: TraceValue
    revision: TraceValue
    config_fingerprint: TraceValue
    policy_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    provenance: Provenance
    unknowns: tuple[TraceUnknown, ...]
    observed_at: TraceValue


@dataclass(frozen=True)
class RollbackReceipt:
    schema_version: int
    receipt_id: str
    change_id: str
    trace_id: TraceValue
    rollback_group_id: TraceValue
    sequence_index: int | None
    parent_receipt_id: TraceValue
    depends_on_receipt_ids: tuple[str, ...]
    rollback_kind: RollbackKind
    rollback_target: ObjectIdentity
    outcome: RollbackOutcome
    observed_pre_rollback: ObjectIdentity
    observed_post_rollback: ObjectIdentity
    confirmation: RestorationConfirmation
    revision: TraceValue
    config_fingerprint: TraceValue
    policy_fingerprint: TraceValue
    evidence_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    provenance: Provenance
    unknowns: tuple[TraceUnknown, ...]
    attempted_at: TraceValue
    confirmed_at: TraceValue
