"""Read-only view for ChangeSet and RollbackReceipt records."""
from __future__ import annotations

from typing import Any

from .model import ChangeSet, RollbackReceipt


def render_change_set(cs: ChangeSet) -> str:
    kind_str = cs.change_kind.value if hasattr(cs.change_kind, "value") else str(cs.change_kind)
    lines = [
        f"change_id: {cs.change_id}",
        f"trace_id: {cs.trace_id or 'unknown'}",
        f"capability: {cs.capability_id} ({cs.subsystem})",
        f"kind: {kind_str}",
        f"before_hash: {cs.before_hash}",
        f"after_hash: {cs.after_hash}",
        f"inverse_operation: {cs.inverse_operation}",
        f"rollback_token: {cs.rollback_token or 'none'}",
        f"authority_class: {cs.authority_class}",
        f"created_at: {cs.created_at.value if cs.created_at else 'unknown'}",
    ]
    if cs.unknowns:
        lines.append("unknowns:")
        for u in cs.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")
    return "\n".join(lines)


def render_rollback_receipt(rr: RollbackReceipt) -> str:
    kind_str = rr.rollback_kind.value if hasattr(rr.rollback_kind, "value") else str(rr.rollback_kind)
    lines = [
        f"receipt_id: {rr.receipt_id}",
        f"change_id: {rr.change_id}",
        f"rollback_kind: {kind_str}",
        f"rollback_target: {rr.rollback_target.value if rr.rollback_target else 'unknown'}",
        f"rollback_outcome: {rr.rollback_outcome.value if rr.rollback_outcome else 'unknown'}",
        f"confirmed_restored_state: {rr.confirmed_restored_state.value if rr.confirmed_restored_state else 'unknown'}",
        f"before_hash: {rr.before_hash}",
        f"after_hash: {rr.after_hash}",
        f"revision: {rr.revision.value if rr.revision else 'unknown'}",
    ]
    if rr.unknowns:
        lines.append("unknowns:")
        for u in rr.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")
    return "\n".join(lines)


class ChangeSetView:
    def __init__(self, change_set: ChangeSet) -> None:
        self._change_set = change_set

    def summary(self) -> str:
        return render_change_set(self._change_set)

    def to_dict(self) -> dict[str, Any]:
        cs = self._change_set
        return {
            "change_id": cs.change_id,
            "trace_id": cs.trace_id,
            "task_id": cs.task_id,
            "session_id": cs.session_id,
            "plan_id": cs.plan_id,
            "capability_id": cs.capability_id,
            "subsystem": cs.subsystem,
            "change_kind": cs.change_kind.value if hasattr(cs.change_kind, "value") else cs.change_kind,
            "before_hash": cs.before_hash,
            "after_hash": cs.after_hash,
            "before_ref": cs.before_ref.value if cs.before_ref else None,
            "after_ref": cs.after_ref.value if cs.after_ref else None,
            "inverse_operation": cs.inverse_operation,
            "rollback_token": cs.rollback_token,
            "revision": cs.revision.value if cs.revision else None,
            "config_fingerprint": cs.config_fingerprint.value if cs.config_fingerprint else None,
            "evidence_refs": list(cs.evidence_refs),
            "authority_class": cs.authority_class,
            "provenance": {
                "origin": cs.provenance.origin,
                "derivation_rule": cs.provenance.derivation_rule,
                "confidence": cs.provenance.confidence,
            },
            "unknowns": [
                {"code": u.code, "field": u.field, "reason": u.reason, "required_for": u.required_for}
                for u in cs.unknowns
            ],
            "created_at": cs.created_at.value if cs.created_at else None,
        }


class RollbackReceiptView:
    def __init__(self, receipt: RollbackReceipt) -> None:
        self._receipt = receipt

    def summary(self) -> str:
        return render_rollback_receipt(self._receipt)

    def to_dict(self) -> dict[str, Any]:
        rr = self._receipt
        return {
            "receipt_id": rr.receipt_id,
            "change_id": rr.change_id,
            "rollback_kind": rr.rollback_kind.value if hasattr(rr.rollback_kind, "value") else rr.rollback_kind,
            "rollback_target": rr.rollback_target.value if rr.rollback_target else None,
            "rollback_outcome": rr.rollback_outcome.value if rr.rollback_outcome else None,
            "confirmed_restored_state": rr.confirmed_restored_state.value if rr.confirmed_restored_state else None,
            "unknowns": [
                {"code": u.code, "field": u.field, "reason": u.reason, "required_for": u.required_for}
                for u in rr.unknowns
            ],
            "provenance": {
                "origin": rr.provenance.origin,
                "derivation_rule": rr.provenance.derivation_rule,
                "confidence": rr.provenance.confidence,
            },
            "before_hash": rr.before_hash,
            "after_hash": rr.after_hash,
            "revision": rr.revision.value if rr.revision else None,
            "config_fingerprint": rr.config_fingerprint.value if rr.config_fingerprint else None,
            "evidence_refs": list(rr.evidence_refs),
            "created_at": rr.created_at.value if rr.created_at else None,
        }
