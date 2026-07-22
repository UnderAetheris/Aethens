"""ChangeSet and RollbackReceipt package.

Provides immutable, additive-only change accountability records and
read-only inspection.  No runtime authority increase.
"""
from __future__ import annotations

from .canonical import canonical_hash, canonical_json, change_id, receipt_id, sha256_hex, sha256_str
from .model import ChangeKind, ChangeSet, RollbackKind, RollbackReceipt
from .view import ChangeSetView, RollbackReceiptView, render_change_set, render_rollback_receipt

__all__ = [
    "ChangeKind",
    "RollbackKind",
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
    "render_change_set",
    "render_rollback_receipt",
]
