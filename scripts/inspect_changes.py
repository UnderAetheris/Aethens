"""Read-only inspection CLI for ChangeSet and RollbackReceipt records."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aetheris.changeset.model import (
    ChangeKind,
    ChangeSet,
    InverseReference,
    MutationDisposition,
    ObjectIdentity,
    Provenance,
    RestorationConfirmation,
    RollbackKind,
    RollbackOutcome,
    RollbackReceipt,
    TraceValue,
)
from aetheris.changeset.validate import (
    validate_change_set,
    validate_rollback_receipt,
)
from aetheris.changeset.view import (
    ChangeSetView,
    RollbackReceiptView,
    render_change_set,
)


MAX_RECORDS = 500
MAX_BYTES = 10 * 1024 * 1024


def _load_json_file(path: Path) -> Any:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"input file exceeds {MAX_BYTES // (1024 * 1024)}MB limit")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list) and len(data) > MAX_RECORDS:
        raise ValueError(f"input record count exceeds {MAX_RECORDS}")
    return data


def _redact_secrets(obj: Any) -> Any:
    if isinstance(obj, str):
        lower = obj.lower()
        for secret in ("secret", "password", "api_key", "token=", "key="):
            if secret in lower:
                return "<redacted>"
        return obj
    if isinstance(obj, dict):
        return {k: _redact_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj


def _coerce_trace_value(v: Any) -> TraceValue:
    if isinstance(v, TraceValue):
        return v
    if isinstance(v, dict):
        return TraceValue(
            state=v.get("state", "unknown"),
            value=v.get("value"),
            reason=v.get("reason") or "",
            source=v.get("source") or "fixture",
        )
    return TraceValue(state="unknown", value=v, reason="coerced", source="fixture")


def _coerce_object_identity(v: Any) -> ObjectIdentity:
    if isinstance(v, ObjectIdentity):
        return v
    if isinstance(v, dict):
        return ObjectIdentity(
            object_type=v.get("object_type", "unknown"),
            scope=v.get("scope", "unknown"),
            locator=_coerce_trace_value(v.get("locator")),
            hash_algorithm=v.get("hash_algorithm", "unknown"),
            digest=_coerce_trace_value(v.get("digest")),
            size_bytes=_coerce_trace_value(v.get("size_bytes")),
            version_ref=_coerce_trace_value(v.get("version_ref")),
        )
    return ObjectIdentity(
        object_type="unknown", scope="unknown",
        locator=_coerce_trace_value(v), hash_algorithm="unknown",
        digest=_coerce_trace_value(None), size_bytes=_coerce_trace_value(None),
        version_ref=_coerce_trace_value(None),
    )


def _coerce_provenance(v: Any) -> Provenance:
    if isinstance(v, Provenance):
        return v
    if isinstance(v, dict):
        return Provenance(
            origin=v.get("origin", "context"),
            derivation_rule=v.get("derivation_rule"),
            source_ids=tuple(v.get("source_ids", ())),
            confidence=v.get("confidence", "unknown"),
        )
    return Provenance(origin="context", confidence="unknown")


def _coerce_change_set(d: dict[str, Any]) -> ChangeSet:
    return ChangeSet(
        schema_version=d.get("schema_version", 1),
        change_id=d.get("change_id", ""),
        trace_id=_coerce_trace_value(d.get("trace_id")),
        task_id=_coerce_trace_value(d.get("task_id")),
        session_id=_coerce_trace_value(d.get("session_id")),
        plan_id=_coerce_trace_value(d.get("plan_id")),
        capability_id=d.get("capability_id", "unknown"),
        owner_subsystem=d.get("owner_subsystem", "unknown"),
        change_kind=ChangeKind(d.get("change_kind", "unknown")),
        disposition=MutationDisposition(d.get("disposition", "unknown")),
        authority_class=d.get("authority_class", "none"),
        target=_coerce_object_identity(d.get("target")),
        before=_coerce_object_identity(d.get("before")),
        after=_coerce_object_identity(d.get("after")),
        inverse=InverseReference(
            kind=RollbackKind(d.get("inverse", {}).get("kind", "unknown")),
            owner_subsystem=d.get("inverse", {}).get("owner_subsystem", "unknown"),
            authority_boundary=d.get("inverse", {}).get("authority_boundary"),
            target=_coerce_trace_value(d.get("inverse", {}).get("target")),
            preconditions=tuple(d.get("inverse", {}).get("preconditions", [])),
            expected_restore_identity=_coerce_object_identity(d.get("inverse", {}).get("expected_restore_identity")),
            authorization_required=_coerce_trace_value(d.get("inverse", {}).get("authorization_required")),
        ),
        rollback_ref=_coerce_trace_value(d.get("rollback_ref")),
        revision=_coerce_trace_value(d.get("revision")),
        config_fingerprint=_coerce_trace_value(d.get("config_fingerprint")),
        policy_fingerprint=_coerce_trace_value(d.get("policy_fingerprint")),
        evidence_refs=tuple(d.get("evidence_refs", [])),
        source_event_ids=tuple(d.get("source_event_ids", [])),
        provenance=_coerce_provenance(d.get("provenance")),
        unknowns=tuple(),
        observed_at=_coerce_trace_value(d.get("observed_at")),
    )


def _coerce_rollback_receipt(d: dict[str, Any]) -> RollbackReceipt:
    return RollbackReceipt(
        schema_version=d.get("schema_version", 1),
        receipt_id=d.get("receipt_id", ""),
        change_id=d.get("change_id", ""),
        trace_id=_coerce_trace_value(d.get("trace_id")),
        rollback_group_id=_coerce_trace_value(d.get("rollback_group_id")),
        sequence_index=d.get("sequence_index"),
        parent_receipt_id=_coerce_trace_value(d.get("parent_receipt_id")),
        depends_on_receipt_ids=tuple(d.get("depends_on_receipt_ids", [])),
        rollback_kind=RollbackKind(d.get("rollback_kind", "unknown")),
        rollback_target=_coerce_object_identity(d.get("rollback_target")),
        outcome=RollbackOutcome(d.get("outcome", "unknown")),
        observed_pre_rollback=_coerce_object_identity(d.get("observed_pre_rollback")),
        observed_post_rollback=_coerce_object_identity(d.get("observed_post_rollback")),
        confirmation=RestorationConfirmation(
            status=d.get("confirmation", {}).get("status", "unknown"),
            expected=_coerce_object_identity(d.get("confirmation", {}).get("expected")),
            observed=_coerce_object_identity(d.get("confirmation", {}).get("observed")),
            verifier=_coerce_trace_value(d.get("confirmation", {}).get("verifier")),
            compared_fields=tuple(d.get("confirmation", {}).get("compared_fields", [])),
            mismatches=tuple(d.get("confirmation", {}).get("mismatches", [])),
        ),
        revision=_coerce_trace_value(d.get("revision")),
        config_fingerprint=_coerce_trace_value(d.get("config_fingerprint")),
        policy_fingerprint=_coerce_trace_value(d.get("policy_fingerprint")),
        evidence_refs=tuple(d.get("evidence_refs", [])),
        source_event_ids=tuple(d.get("source_event_ids", [])),
        provenance=_coerce_provenance(d.get("provenance")),
        unknowns=tuple(),
        attempted_at=_coerce_trace_value(d.get("attempted_at")),
        confirmed_at=_coerce_trace_value(d.get("confirmed_at")),
    )


def _print_summary(records: list[dict[str, Any]]) -> int:
    for rec in records:
        try:
            cs = _coerce_change_set(rec)
            print(render_change_set(cs))
        except Exception as exc:
            print(f"FAIL change_set: {exc}", file=sys.stderr)
    return 0


def _print_json(records: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> int:
    output: dict[str, Any] = {}
    change_sets = []
    for rec in records:
        try:
            cs = _coerce_change_set(rec)
            validation = validate_change_set(cs)
            view = ChangeSetView(cs)
            entry = {
                "record": rec,
                "validation": {
                    "valid": validation.valid,
                    "errors": list(validation.errors),
                    "warnings": list(validation.warnings),
                },
                "view": view.to_dict(),
            }
            change_sets.append(entry)
        except Exception as exc:
            change_sets.append({"record": rec, "validation": {"valid": False, "errors": [str(exc)], "warnings": []}})
    output["change_sets"] = change_sets

    rr_list = []
    for rec in receipts:
        try:
            rr = _coerce_rollback_receipt(rec)
            validation = validate_rollback_receipt(rr)
            rr_view = RollbackReceiptView(rr)
            entry = {
                "record": rec,
                "validation": {
                    "valid": validation.valid,
                    "errors": list(validation.errors),
                    "warnings": list(validation.warnings),
                },
                "view": rr_view.to_dict(),
            }
            rr_list.append(entry)
        except Exception as exc:
            rr_list.append({"record": rec, "validation": {"valid": False, "errors": [str(exc)], "warnings": []}})
    output["rollback_receipts"] = rr_list

    print(json.dumps(_redact_secrets(output), indent=2, sort_keys=True))
    return 0


def _validate_only(records: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> int:
    exit_code = 0
    for rec in records:
        try:
            cs = _coerce_change_set(rec)
            validation = validate_change_set(cs)
            if not validation.valid:
                print(f"INVALID change_set {rec.get('change_id', '?')}: {'; '.join(validation.errors)}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"VALID change_set {rec.get('change_id', '?')}")
        except Exception as exc:
            print(f"FAIL change_set: {exc}", file=sys.stderr)
            exit_code = 1
    for rec in receipts:
        try:
            rr = _coerce_rollback_receipt(rec)
            validation = validate_rollback_receipt(rr)
            if not validation.valid:
                print(f"INVALID receipt {rec.get('receipt_id', '?')}: {'; '.join(validation.errors)}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"VALID receipt {rec.get('receipt_id', '?')}")
        except Exception as exc:
            print(f"FAIL receipt: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only ChangeSet/RollbackReceipt inspector")
    parser.add_argument("--changes", required=True, type=Path, help="Path to change_set JSON array")
    parser.add_argument("--receipts", type=Path, default=None, help="Path to rollback_receipt JSON array")
    parser.add_argument("--format", choices=["summary", "json"], default="summary")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    if not args.changes.exists():
        print(f"changes file not found: {args.changes}", file=sys.stderr)
        return 2
    if args.receipts and not args.receipts.exists():
        print(f"receipts file not found: {args.receipts}", file=sys.stderr)
        return 2

    try:
        records = _load_json_file(args.changes)
    except Exception as exc:
        print(f"failed to load changes: {exc}", file=sys.stderr)
        return 2
    if not isinstance(records, list):
        print("changes file must contain a JSON array", file=sys.stderr)
        return 2

    receipts = []
    if args.receipts:
        try:
            receipts = _load_json_file(args.receipts)
        except Exception as exc:
            print(f"failed to load receipts: {exc}", file=sys.stderr)
            return 2
        if not isinstance(receipts, list):
            print("receipts file must contain a JSON array", file=sys.stderr)
            return 2

    if args.validate_only:
        return _validate_only(records, receipts)

    if args.format == "summary":
        return _print_summary(records)
    return _print_json(records, receipts)


if __name__ == "__main__":
    sys.exit(main())
