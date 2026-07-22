"""Canonical JSON, hashing, and deterministic identity for ChangeSet and RollbackReceipt."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .model import ChangeSet, RollbackReceipt


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_str(text: str) -> str:
    return sha256_hex(text.encode("utf-8"))


def canonical_hash(value: Any) -> str:
    from dataclasses import asdict
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return sha256_str(canonical_json(value))


def change_id(change: ChangeSet) -> str:
    preimage = "|".join([
        "changeset",
        "v1",
        change.subsystem,
        change.capability_id,
        change.change_kind,
        change.before_hash,
        change.after_hash,
        str(change.created_at.value),
    ])
    return "chg_" + sha256_str(preimage)[:32]


def receipt_id(receipt: RollbackReceipt) -> str:
    preimage = "|".join([
        "rollback_receipt",
        "v1",
        receipt.change_id,
        receipt.rollback_kind,
        receipt.before_hash,
        receipt.after_hash,
        str(receipt.created_at.value),
    ])
    return "rcpt_" + sha256_str(preimage)[:32]
