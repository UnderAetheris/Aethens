"""Canonical JSON and deterministic identity helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Return a stable, deterministic JSON serialization.

    Uses sort_keys=True, compact separators, and rejects NaN/Infinity.
    """
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
    return sha256_str(canonical_json(value))


def source_hash(raw_bytes: bytes) -> str:
    return sha256_hex(raw_bytes)


def payload_hash(payload: Any) -> str:
    return canonical_hash(payload)


def event_id(
    schema_version: int,
    adapter_id: str,
    adapter_version: int,
    stream_id: str,
    line_or_key: int | str | None,
    identity_basis: str,
) -> str:
    """Derive a deterministic event ID.

    Preimage: schema_version | adapter_id | adapter_version | stream_id |
    line_or_key | identity_basis
    """
    preimage = "|".join([
        str(schema_version),
        adapter_id,
        str(adapter_version),
        stream_id,
        str(line_or_key) if line_or_key is not None else "",
        identity_basis,
    ])
    return "evt_" + sha256_str(preimage)[:32]
