"""ChangeSet and RollbackReceipt package.

Provides immutable, additive-only change accountability records and
read-only inspection.  No runtime authority increase.
"""
from __future__ import annotations

from .canonical import (
    canonical_hash,
    canonical_json,
    change_id,
    receipt_id,
    sha256_hex,
    sha256_str,
    make_change_set,
    make_rollback_receipt,
)
from .model import (
    ChangeKind,
    ChangeSet,
    InverseReference,
    MutationDisposition,
    ObjectIdentity,
    RestorationConfirmation,
    RollbackKind,
    RollbackOutcome,
    RollbackReceipt,
)
from .projector import (
    ChangeSetProjector,
    MutationEvidence,
    ProjectionResult,
    ReceiptProjector,
    change_set_to_envelope,
    rollback_receipt_to_envelope,
)
from .validate import (
    ValidationResult,
    validate_change_set,
    validate_rollback_receipt,
)
from .view import (
    ChangeSetView,
    RollbackReceiptView,
    render_change_set,
    render_rollback_receipt,
)

__all__ = [
    "ChangeKind",
    "MutationDisposition",
    "RollbackKind",
    "RollbackOutcome",
    "ObjectIdentity",
    "InverseReference",
    "RestorationConfirmation",
    "ChangeSet",
    "RollbackReceipt",
    "ChangeSetView",
    "RollbackReceiptView",
    "canonical_json",
    "canonical_hash",
    "sha256_hex",
    "sha256_str",
    "change_id",
    "receipt_id",
    "make_change_set",
    "make_rollback_receipt",
    "validate_change_set",
    "validate_rollback_receipt",
    "ValidationResult",
    "ChangeSetProjector",
    "ReceiptProjector",
    "MutationEvidence",
    "ProjectionResult",
    "change_set_to_envelope",
    "rollback_receipt_to_envelope",
    "render_change_set",
    "render_rollback_receipt",
]
