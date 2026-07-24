"""Pure validation for ChangeSet and RollbackReceipt records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import change_id, receipt_id, make_change_set as _make_change_set_factory, make_rollback_receipt as _make_rollback_receipt_factory
from .model import (
    ChangeKind,
    ChangeSet,
    MutationDisposition,
    ObjectIdentity,
    RollbackKind,
    RollbackOutcome,
    RollbackReceipt,
    TraceUnknown,
    TraceValue,
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def _tv_repr(tv: TraceValue) -> tuple[str, Any]:
    return (tv.state, tv.value)


def _id_preimage(identity: ObjectIdentity) -> dict[str, Any]:
    return {
        "object_type": identity.object_type,
        "scope": identity.scope,
        "locator": _tv_repr(identity.locator),
        "hash_algorithm": identity.hash_algorithm,
        "digest": _tv_repr(identity.digest),
        "size_bytes": _tv_repr(identity.size_bytes),
        "version_ref": _tv_repr(identity.version_ref),
    }


def make_change_set(**kwargs: Any) -> ChangeSet:
    return _make_change_set_factory(**kwargs)


def make_rollback_receipt(**kwargs: Any) -> RollbackReceipt:
    return _make_rollback_receipt_factory(**kwargs)


def _validate_sha256_digest(identity: ObjectIdentity, field: str) -> list[str]:
    errors: list[str] = []
    if identity.hash_algorithm == "sha256":
        if identity.digest.state == "known" and identity.digest.value is not None:
            d = str(identity.digest.value)
            if not (len(d) == 64 and all(c in "0123456789abcdef" for c in d)):
                errors.append(f"{field} sha256 digest must be exactly 64 lowercase hex characters: {d!r}")
    return errors


def _validate_object_identity(identity: ObjectIdentity, label: str) -> list[str]:
    errors: list[str] = []
    if not identity.object_type:
        errors.append(f"{label}.object_type must be non-empty")
    if not identity.scope:
        errors.append(f"{label}.scope must be non-empty")
    errors.extend(_validate_sha256_digest(identity, f"{label}.digest"))
    return errors


_NON_EXECUTABLE_ROLLBACK_KINDS = {
    RollbackKind.GIT_REVERT,
    RollbackKind.RESTORE_SNAPSHOT,
    RollbackKind.TOMBSTONE_UNRETIRE,
    RollbackKind.CONFIG_DISABLE,
    RollbackKind.DISCARD_SANDBOX,
    RollbackKind.RESUME_CHECKPOINT,
    RollbackKind.NOT_APPLICABLE,
}

_APPEND_ONLY_DISPOSITIONS = {
    MutationDisposition.APPEND_ONLY,
    MutationDisposition.EPHEMERAL,
}
_RESEARCH_APPEND_KINDS = {
    ChangeKind.RESEARCH_EVIDENCE_APPEND,
    ChangeKind.JOURNAL_APPEND,
    ChangeKind.KNOWLEDGE_APPEND,
}

_DANGEROUS_INVERSE_PATTERNS = {
    "disable_safety", "bypass_review", "expand_allowlist",
    "increase_budget", "grant_permission", "add_tool",
    "delete_evidence", "truncate_evidence", "remove_evidence",
    "override_safety", "skip_review", "elevate_privilege",
    "exec", "execute", "callback", "command",
}


def _check_dangerous_inverse(inverse: Any) -> list[str]:
    errors: list[str] = []
    target_val = ""
    if hasattr(inverse, "target") and isinstance(inverse.target, TraceValue):
        target_val = str(inverse.target.value or "").lower()
    elif isinstance(inverse, dict):
        target_val = str(inverse.get("target", {}).get("value", "")).lower()
    for pattern in _DANGEROUS_INVERSE_PATTERNS:
        if pattern in target_val:
            errors.append(f"inverse reference target contains dangerous pattern: {pattern}")
    return errors


def validate_change_set(record: ChangeSet | dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(record, dict):
        try:
            record = make_change_set(**record)
        except Exception as exc:
            return ValidationResult(valid=False, errors=(f"construction failed: {exc}",), warnings=())

    cs = record
    if not isinstance(cs.change_kind, ChangeKind):
        errors.append(f"change_kind must be a ChangeKind enum value, got: {cs.change_kind!r}")
    if not isinstance(cs.disposition, MutationDisposition):
        errors.append(f"disposition must be a MutationDisposition enum value, got: {cs.disposition!r}")
    if not isinstance(cs.inverse.kind, RollbackKind):
        errors.append(f"inverse.kind must be a RollbackKind enum value, got: {cs.inverse.kind!r}")

    if not cs.change_id.startswith("chg_"):
        errors.append("change_id must start with chg_")
    try:
        expected_id = change_id(cs)
        if cs.change_id != expected_id:
            errors.append(f"change_id does not match content: {cs.change_id!r} != {expected_id!r}")
    except Exception as exc:
        errors.append(f"change_id derivation failed: {exc}")

    if cs.schema_version != 1:
        errors.append(f"unsupported schema_version: {cs.schema_version}")

    # Blocker 9: collect _validate_object_identity errors into final result
    errors.extend(_validate_object_identity(cs.target, "target"))
    errors.extend(_validate_object_identity(cs.before, "before"))
    errors.extend(_validate_object_identity(cs.after, "after"))

    if cs.target.scope != cs.before.scope or cs.target.object_type != cs.before.object_type:
        if not (cs.before.locator.state == "unknown" and cs.before.digest.state == "unknown"
                and cs.before.hash_algorithm == "unknown"):
            errors.append("before scope/type must match target for direct restoration claims")
    if cs.target.scope != cs.after.scope or cs.target.object_type != cs.after.object_type:
        if not (cs.after.locator.state == "unknown" and cs.after.digest.state == "unknown"
                and cs.after.hash_algorithm == "unknown"):
            errors.append("after scope/type must match target for direct restoration claims")

    if cs.inverse.executable is not False:
        errors.append("inverse reference must have executable=False")

    # Blocker 8: explicit validator rejection for dangerous inverse references
    errors.extend(_check_dangerous_inverse(cs.inverse))

    if cs.inverse.kind not in _NON_EXECUTABLE_ROLLBACK_KINDS:
        errors.append(f"unknown rollback kind in inverse reference: {cs.inverse.kind}")

    if not cs.owner_subsystem:
        errors.append("owner_subsystem must be non-empty")
    if not cs.capability_id:
        errors.append("capability_id must be non-empty")

    if cs.change_kind not in ChangeKind:
        errors.append(f"unknown change_kind: {cs.change_kind}")

    if cs.disposition not in MutationDisposition:
        errors.append(f"unknown disposition: {cs.disposition}")

    if (cs.disposition in _APPEND_ONLY_DISPOSITIONS or cs.change_kind in _RESEARCH_APPEND_KINDS):
        if cs.inverse.kind not in (RollbackKind.NOT_APPLICABLE, RollbackKind.UNKNOWN):
            errors.append("append-only mutation requires inverse.kind not_applicable or unknown")

    for u in cs.unknowns:
        if u.code not in TraceUnknown.__annotations__.get("code", ()) and u.code not in {
            "missing_raw_bytes", "missing_parent", "missing_cause",
        }:
            warnings.append(f"non-standard unknown code: {u.code}")

    return ValidationResult(valid=not errors, errors=tuple(errors), warnings=tuple(warnings))


def validate_rollback_receipt(
    record: RollbackReceipt | dict[str, Any],
    change_set: ChangeSet | None = None,
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if isinstance(record, dict):
        try:
            record = make_rollback_receipt(**record)
        except Exception as exc:
            return ValidationResult(valid=False, errors=(f"construction failed: {exc}",), warnings=())

    rr = record
    if not rr.receipt_id.startswith("rcpt_"):
        errors.append("receipt_id must start with rcpt_")
    expected_id = receipt_id(rr)
    if rr.receipt_id != expected_id:
        errors.append(f"receipt_id does not match content: {rr.receipt_id!r} != {expected_id!r}")

    if rr.schema_version != 1:
        errors.append(f"unsupported schema_version: {rr.schema_version}")

    if change_set is not None:
        if rr.change_id != change_set.change_id:
            errors.append(f"receipt.change_id {rr.change_id!r} does not match linked change_set {change_set.change_id!r}")
        if rr.trace_id.state != "unknown" and change_set.trace_id.state != "unknown":
            if _tv_repr(rr.trace_id) != _tv_repr(change_set.trace_id):
                errors.append("receipt trace_id must match linked change_set trace_id when both known")

        if rr.rollback_kind == RollbackKind.NOT_APPLICABLE:
            pass
        else:
            if rr.rollback_target.scope != change_set.target.scope or rr.rollback_target.object_type != change_set.target.object_type:
                errors.append("receipt.rollback_target scope/type must match change_set.target")
            pre_digest = rr.observed_pre_rollback.digest
            after_digest = change_set.after.digest
            if pre_digest.state == "known" and after_digest.state == "known":
                if str(pre_digest.value) != str(after_digest.value):
                    errors.append("receipt.observed_pre_rollback.digest must match change_set.after.digest")
            exp = rr.confirmation.expected
            before_digest = change_set.before.digest
            if exp is not None:
                exp_digest = exp.digest
                if exp_digest.state == "known" and before_digest.state == "known":
                    if str(exp_digest.value) != str(before_digest.value):
                        errors.append("receipt.confirmation.expected must match change_set.before.digest")
            obs_digest = rr.observed_post_rollback.digest
            if obs_digest.state == "known" and before_digest.state == "known":
                if str(obs_digest.value) != str(before_digest.value):
                    errors.append("receipt.observed_post_rollback.digest must match change_set.before.digest")

        if rr.confirmation.status == "confirmed":
            if rr.outcome != RollbackOutcome.SUCCEEDED:
                errors.append("confirmed restoration requires succeeded outcome")
            exp = rr.confirmation.expected
            obs = rr.confirmation.observed
            if exp is None or obs is None:
                errors.append("confirmed restoration requires known expected and observed identity")
            else:
                if exp.object_type != obs.object_type or exp.scope != obs.scope:
                    errors.append("confirmed restoration requires same object type and scope")
                if exp.digest.state != "known" or obs.digest.state != "known":
                    errors.append("confirmed restoration requires known digests")
                elif str(exp.digest.value) != str(obs.digest.value):
                    errors.append("confirmed restoration requires matching digests")
                if rr.confirmation.verifier.state != "known":
                    errors.append("confirmed restoration requires known verifier provenance")
                if rr.confirmation.mismatches:
                    errors.append("confirmed restoration cannot have mismatches")
                for u in rr.unknowns:
                    if u.code not in {"missing_config", "missing_policy"}:
                        errors.append(f"confirmed restoration cannot have required unknowns: {u.code}")

        if change_set is not None:
            disp = change_set.disposition
            kind = change_set.change_kind
            if disp in _APPEND_ONLY_DISPOSITIONS or kind in _RESEARCH_APPEND_KINDS:
                if rr.outcome in (RollbackOutcome.SUCCEEDED, RollbackOutcome.PARTIAL):
                    warnings.append(
                        "rollback reported success on append-only evidence; verify no evidence was destroyed"
                    )

        if rr.rollback_kind == RollbackKind.CONFIG_DISABLE:
            if change_set is not None and change_set.disposition == MutationDisposition.APPEND_ONLY:
                errors.append("config_disable is not valid for append-only mutations")
        if rr.rollback_kind == RollbackKind.RESUME_CHECKPOINT:
            if change_set is not None and change_set.disposition not in (
                MutationDisposition.REBUILDABLE_SNAPSHOT,
                MutationDisposition.EPHEMERAL,
            ):
                errors.append("resume_checkpoint is valid only for rebuildable_snapshot or ephemeral control state")
        if rr.rollback_kind == RollbackKind.DISCARD_SANDBOX:
            if rr.rollback_target.scope != "sandbox":
                errors.append("discard_sandbox applies only to sandbox scope")

    if rr.rollback_kind == RollbackKind.UNKNOWN:
        errors.append("wildcard rollback kind UNKNOWN is not permitted in receipts")

    if rr.sequence_index is not None and rr.sequence_index < 0:
        errors.append("sequence_index must be non-negative when present")

    for u in rr.unknowns:
        if u.code not in TraceUnknown.__annotations__.get("code", ()) and u.code not in {
            "missing_raw_bytes", "missing_parent", "missing_cause",
        }:
            warnings.append(f"non-standard unknown code: {u.code}")

    return ValidationResult(valid=not errors, errors=tuple(errors), warnings=tuple(warnings))
