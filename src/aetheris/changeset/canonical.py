"""Canonical JSON, hashing, and deterministic identity for ChangeSet and RollbackReceipt."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from .model import (
    ChangeSet,
    ObjectIdentity,
    RollbackReceipt,
    TraceValue,
)


def _to_serializable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    value = _to_serializable(value)
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
    value = _to_serializable(value)
    return sha256_str(canonical_json(value))


def _tv_state_value(tv: TraceValue) -> tuple[str, Any]:
    return (tv.state, tv.value)


def _identity_preimage(identity: ObjectIdentity) -> dict[str, Any]:
    return {
        "object_type": identity.object_type,
        "scope": identity.scope,
        "locator": _tv_state_value(identity.locator),
        "hash_algorithm": identity.hash_algorithm,
        "digest": _tv_state_value(identity.digest),
        "size_bytes": _tv_state_value(identity.size_bytes),
        "version_ref": _tv_state_value(identity.version_ref),
    }


def change_id(change: ChangeSet) -> str:
    preimage = {
        "schema_version": change.schema_version,
        "trace_id": _tv_state_value(change.trace_id),
        "capability_id": change.capability_id,
        "owner_subsystem": change.owner_subsystem,
        "change_kind": change.change_kind.value,
        "disposition": change.disposition.value,
        "target": _identity_preimage(change.target),
        "before": _identity_preimage(change.before),
        "after": _identity_preimage(change.after),
        "revision": _tv_state_value(change.revision),
        "source_event_ids": change.source_event_ids,
        "observed_at": _tv_state_value(change.observed_at),
    }
    return "chg_" + sha256_str(canonical_json(preimage))[:32]


def receipt_id(receipt: RollbackReceipt) -> str:
    preimage = {
        "schema_version": receipt.schema_version,
        "change_id": receipt.change_id,
        "rollback_group_id": _tv_state_value(receipt.rollback_group_id),
        "sequence_index": receipt.sequence_index,
        "rollback_kind": receipt.rollback_kind.value,
        "rollback_target": _identity_preimage(receipt.rollback_target),
        "observed_pre_rollback": _identity_preimage(receipt.observed_pre_rollback),
        "observed_post_rollback": _identity_preimage(receipt.observed_post_rollback),
        "outcome": receipt.outcome.value,
        "confirmation": {
            "status": receipt.confirmation.status,
            "expected": _identity_preimage(receipt.confirmation.expected) if receipt.confirmation.expected else None,
            "observed": _identity_preimage(receipt.confirmation.observed) if receipt.confirmation.observed else None,
            "verifier": _tv_state_value(receipt.confirmation.verifier),
            "compared_fields": receipt.confirmation.compared_fields,
            "mismatches": receipt.confirmation.mismatches,
        },
        "revision": _tv_state_value(receipt.revision),
        "source_event_ids": receipt.source_event_ids,
        "attempted_at": _tv_state_value(receipt.attempted_at),
    }
    return "rcpt_" + sha256_str(canonical_json(preimage))[:32]


def make_change_set(**kwargs: Any) -> "ChangeSet":
    kwargs.setdefault("schema_version", 1)
    cs = ChangeSet(**kwargs)
    expected = change_id(cs)
    if cs.change_id != expected:
        cs = ChangeSet(change_id=expected, **{f.name: getattr(cs, f.name) for f in ChangeSet.__dataclass_fields__.values() if f.name != "change_id"})
    return cs


def make_rollback_receipt(**kwargs: Any) -> "RollbackReceipt":
    kwargs.setdefault("schema_version", 1)
    rr = RollbackReceipt(**kwargs)
    expected = receipt_id(rr)
    if rr.receipt_id != expected:
        rr = RollbackReceipt(receipt_id=expected, **{f.name: getattr(rr, f.name) for f in RollbackReceipt.__dataclass_fields__.values() if f.name != "receipt_id"})
    return rr
