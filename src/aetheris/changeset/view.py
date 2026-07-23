"""Read-only view for ChangeSet and RollbackReceipt records."""
from __future__ import annotations

from typing import Any

from .model import (
    ChangeSet,
    RollbackReceipt,
    TraceValue,
)


def _tv_display(tv: Any) -> str:
    if isinstance(tv, TraceValue):
        if tv.state == "known":
            return str(tv.value)
        return f"<{tv.state}:{tv.reason or ''}>"
    return str(tv)


def _kind_display(kind: Any) -> str:
    return kind.value if hasattr(kind, "value") else str(kind)


def render_change_set(cs: ChangeSet) -> str:
    lines = [
        f"change_id: {cs.change_id}",
        f"schema_version: {cs.schema_version}",
        f"trace_id: {_tv_display(cs.trace_id)}",
        f"task_id: {_tv_display(cs.task_id)}",
        f"session_id: {_tv_display(cs.session_id)}",
        f"plan_id: {_tv_display(cs.plan_id)}",
        f"capability: {cs.capability_id} ({cs.owner_subsystem})",
        f"kind: {_kind_display(cs.change_kind)}",
        f"disposition: {_kind_display(cs.disposition)}",
        f"authority_class: {cs.authority_class}",
        f"target: {_tv_display(cs.target.locator)} scope={cs.target.scope} type={cs.target.object_type}",
        f"before: {_tv_display(cs.before.locator)} hash={_tv_display(cs.before.digest)}",
        f"after: {_tv_display(cs.after.locator)} hash={_tv_display(cs.after.digest)}",
        f"inverse_kind: {_kind_display(cs.inverse.kind)} owner={cs.inverse.owner_subsystem}",
        f"rollback_ref: {_tv_display(cs.rollback_ref)}",
        f"revision: {_tv_display(cs.revision)}",
        f"config_fingerprint: {_tv_display(cs.config_fingerprint)}",
        f"policy_fingerprint: {_tv_display(cs.policy_fingerprint)}",
        f"evidence_refs: {cs.evidence_refs}",
        f"source_event_ids: {cs.source_event_ids}",
        f"observed_at: {_tv_display(cs.observed_at)}",
        f"provenance: {cs.provenance.origin} confidence={cs.provenance.confidence}",
    ]
    if cs.unknowns:
        lines.append("unknowns:")
        for u in cs.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")
    return "\n".join(lines)


def render_rollback_receipt(rr: RollbackReceipt) -> str:
    lines = [
        f"receipt_id: {rr.receipt_id}",
        f"schema_version: {rr.schema_version}",
        f"change_id: {rr.change_id}",
        f"trace_id: {_tv_display(rr.trace_id)}",
        f"rollback_group_id: {_tv_display(rr.rollback_group_id)}",
        f"sequence_index: {rr.sequence_index}",
        f"parent_receipt_id: {_tv_display(rr.parent_receipt_id)}",
        f"depends_on_receipt_ids: {rr.depends_on_receipt_ids}",
        f"rollback_kind: {_kind_display(rr.rollback_kind)}",
        f"outcome: {_kind_display(rr.outcome)}",
        f"rollback_target: {_tv_display(rr.rollback_target)}",
        f"observed_pre_rollback: {_tv_display(rr.observed_pre_rollback)}",
        f"observed_post_rollback: {_tv_display(rr.observed_post_rollback)}",
        f"confirmation_status: {rr.confirmation.status}",
        f"confirmation_expected: {_tv_display(rr.confirmation.expected) if rr.confirmation.expected else 'none'}",
        f"confirmation_observed: {_tv_display(rr.confirmation.observed) if rr.confirmation.observed else 'none'}",
        f"confirmation_verifier: {_tv_display(rr.confirmation.verifier)}",
        f"confirmation_mismatches: {rr.confirmation.mismatches}",
        f"revision: {_tv_display(rr.revision)}",
        f"config_fingerprint: {_tv_display(rr.config_fingerprint)}",
        f"policy_fingerprint: {_tv_display(rr.policy_fingerprint)}",
        f"evidence_refs: {rr.evidence_refs}",
        f"source_event_ids: {rr.source_event_ids}",
        f"attempted_at: {_tv_display(rr.attempted_at)}",
        f"confirmed_at: {_tv_display(rr.confirmed_at)}",
        f"provenance: {rr.provenance.origin} confidence={rr.provenance.confidence}",
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
            "schema_version": cs.schema_version,
            "change_id": cs.change_id,
            "trace_id": cs.trace_id.value if cs.trace_id else None,
            "task_id": cs.task_id.value if cs.task_id else None,
            "session_id": cs.session_id.value if cs.session_id else None,
            "plan_id": cs.plan_id.value if cs.plan_id else None,
            "capability_id": cs.capability_id,
            "owner_subsystem": cs.owner_subsystem,
            "change_kind": _kind_display(cs.change_kind),
            "disposition": _kind_display(cs.disposition),
            "authority_class": cs.authority_class,
            "target": {
                "object_type": cs.target.object_type,
                "scope": cs.target.scope,
                "locator": cs.target.locator.value,
                "hash_algorithm": cs.target.hash_algorithm,
                "digest": cs.target.digest.value,
                "size_bytes": cs.target.size_bytes.value,
                "version_ref": cs.target.version_ref.value,
            },
            "before": {
                "object_type": cs.before.object_type,
                "scope": cs.before.scope,
                "locator": cs.before.locator.value,
                "hash_algorithm": cs.before.hash_algorithm,
                "digest": cs.before.digest.value,
                "size_bytes": cs.before.size_bytes.value,
                "version_ref": cs.before.version_ref.value,
            },
            "after": {
                "object_type": cs.after.object_type,
                "scope": cs.after.scope,
                "locator": cs.after.locator.value,
                "hash_algorithm": cs.after.hash_algorithm,
                "digest": cs.after.digest.value,
                "size_bytes": cs.after.size_bytes.value,
                "version_ref": cs.after.version_ref.value,
            },
            "inverse": {
                "kind": _kind_display(cs.inverse.kind),
                "owner_subsystem": cs.inverse.owner_subsystem,
                "authority_boundary": cs.inverse.authority_boundary,
                "target": cs.inverse.target.value,
                "preconditions": list(cs.inverse.preconditions),
                "expected_restore_identity": {
                    "object_type": cs.inverse.expected_restore_identity.object_type,
                    "scope": cs.inverse.expected_restore_identity.scope,
                    "digest": cs.inverse.expected_restore_identity.digest.value,
                } if cs.inverse.expected_restore_identity else None,
                "authorization_required": cs.inverse.authorization_required.value,
                "executable": cs.inverse.executable,
            },
            "rollback_ref": cs.rollback_ref.value if cs.rollback_ref else None,
            "revision": cs.revision.value if cs.revision else None,
            "config_fingerprint": cs.config_fingerprint.value if cs.config_fingerprint else None,
            "policy_fingerprint": cs.policy_fingerprint.value if cs.policy_fingerprint else None,
            "evidence_refs": list(cs.evidence_refs),
            "source_event_ids": list(cs.source_event_ids),
            "provenance": {
                "origin": cs.provenance.origin,
                "derivation_rule": cs.provenance.derivation_rule,
                "confidence": cs.provenance.confidence,
            },
            "unknowns": [
                {"code": u.code, "field": u.field, "reason": u.reason, "required_for": u.required_for}
                for u in cs.unknowns
            ],
            "observed_at": cs.observed_at.value if cs.observed_at else None,
            "validation": None,
        }


class RollbackReceiptView:
    def __init__(self, receipt: RollbackReceipt) -> None:
        self._receipt = receipt

    def summary(self) -> str:
        return render_rollback_receipt(self._receipt)

    def to_dict(self) -> dict[str, Any]:
        rr = self._receipt
        return {
            "schema_version": rr.schema_version,
            "receipt_id": rr.receipt_id,
            "change_id": rr.change_id,
            "trace_id": rr.trace_id.value if rr.trace_id else None,
            "rollback_group_id": rr.rollback_group_id.value if rr.rollback_group_id else None,
            "sequence_index": rr.sequence_index,
            "parent_receipt_id": rr.parent_receipt_id.value if rr.parent_receipt_id else None,
            "depends_on_receipt_ids": list(rr.depends_on_receipt_ids),
            "rollback_kind": _kind_display(rr.rollback_kind),
            "rollback_target": {
                "object_type": rr.rollback_target.object_type,
                "scope": rr.rollback_target.scope,
                "locator": rr.rollback_target.locator.value,
                "hash_algorithm": rr.rollback_target.hash_algorithm,
                "digest": rr.rollback_target.digest.value,
                "size_bytes": rr.rollback_target.size_bytes.value,
                "version_ref": rr.rollback_target.version_ref.value,
            },
            "outcome": _kind_display(rr.outcome),
            "observed_pre_rollback": {
                "object_type": rr.observed_pre_rollback.object_type,
                "scope": rr.observed_pre_rollback.scope,
                "locator": rr.observed_pre_rollback.locator.value,
                "digest": rr.observed_pre_rollback.digest.value,
            },
            "observed_post_rollback": {
                "object_type": rr.observed_post_rollback.object_type,
                "scope": rr.observed_post_rollback.scope,
                "locator": rr.observed_post_rollback.locator.value,
                "digest": rr.observed_post_rollback.digest.value,
            },
            "confirmation": {
                "status": rr.confirmation.status,
                "expected": {
                    "object_type": rr.confirmation.expected.object_type,
                    "scope": rr.confirmation.expected.scope,
                    "locator": rr.confirmation.expected.locator.value,
                    "digest": rr.confirmation.expected.digest.value,
                } if rr.confirmation.expected else None,
                "observed": {
                    "object_type": rr.confirmation.observed.object_type,
                    "scope": rr.confirmation.observed.scope,
                    "locator": rr.confirmation.observed.locator.value,
                    "digest": rr.confirmation.observed.digest.value,
                } if rr.confirmation.observed else None,
                "verifier": rr.confirmation.verifier.value,
                "compared_fields": list(rr.confirmation.compared_fields),
                "mismatches": list(rr.confirmation.mismatches),
            },
            "revision": rr.revision.value if rr.revision else None,
            "config_fingerprint": rr.config_fingerprint.value if rr.config_fingerprint else None,
            "policy_fingerprint": rr.policy_fingerprint.value if rr.policy_fingerprint else None,
            "evidence_refs": list(rr.evidence_refs),
            "source_event_ids": list(rr.source_event_ids),
            "provenance": {
                "origin": rr.provenance.origin,
                "derivation_rule": rr.provenance.derivation_rule,
                "confidence": rr.provenance.confidence,
            },
            "unknowns": [
                {"code": u.code, "field": u.field, "reason": u.reason, "required_for": u.required_for}
                for u in rr.unknowns
            ],
            "attempted_at": rr.attempted_at.value if rr.attempted_at else None,
            "confirmed_at": rr.confirmed_at.value if rr.confirmed_at else None,
            "validation": None,
        }
