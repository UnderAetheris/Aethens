"""Tests for CLI validation linkage (Blocker 7)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts.inspect_changes import main


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_validate_only_checks_receipt_against_linked_changeset():
    cs_data = {
        "schema_version": 1,
        "change_id": "chg_test",
        "trace_id": {"state": "known", "value": "t1", "source": "test"},
        "task_id": {"state": "known", "value": "t1", "source": "test"},
        "session_id": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "plan_id": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "capability_id": "test",
        "owner_subsystem": "test",
        "change_kind": "file_edit",
        "disposition": "reversible",
        "authority_class": "none",
        "target": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "x", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "before": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "after": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "new", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "inverse": {"kind": "git_revert", "owner_subsystem": "test", "authority_boundary": None, "target": {"state": "known", "value": "x", "source": "test"}, "preconditions": [], "expected_restore_identity": None, "authorization_required": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "executable": False},
        "rollback_ref": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "revision": {"state": "known", "value": "r1", "source": "test"},
        "config_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "policy_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "evidence_refs": [],
        "source_event_ids": [],
        "provenance": {"origin": "persisted", "derivation_rule": None, "source_ids": [], "confidence": "exact"},
        "unknowns": [],
        "observed_at": {"state": "known", "value": 1000.0, "source": "test"},
    }
    rr_data = {
        "schema_version": 1,
        "receipt_id": "rcpt_test",
        "change_id": "chg_test",
        "trace_id": {"state": "known", "value": "t1", "source": "test"},
        "rollback_group_id": {"state": "known", "value": "grp_chg_test", "source": "test"},
        "sequence_index": 0,
        "parent_receipt_id": {"state": "not_applicable", "value": None, "reason": "first", "source": "test"},
        "depends_on_receipt_ids": [],
        "rollback_kind": "git_revert",
        "rollback_target": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "x", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "outcome": "succeeded",
        "observed_pre_rollback": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "new", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "observed_post_rollback": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "confirmation": {"status": "confirmed", "expected": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}}, "observed": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}}, "verifier": {"state": "known", "value": "v", "source": "test"}, "compared_fields": ["object_type", "scope", "digest"], "mismatches": []},
        "revision": {"state": "known", "value": "r1", "source": "test"},
        "config_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "policy_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "evidence_refs": [],
        "source_event_ids": [],
        "provenance": {"origin": "persisted", "derivation_rule": None, "source_ids": [], "confidence": "exact"},
        "unknowns": [],
        "attempted_at": {"state": "known", "value": 1000.0, "source": "test"},
        "confirmed_at": {"state": "known", "value": 1010.0, "source": "test"},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        cs_path = Path(tmpdir) / "changes.json"
        rr_path = Path(tmpdir) / "receipts.json"
        _write_json(cs_path, [cs_data])
        _write_json(rr_path, [rr_data])
        rc = main(["--changes", str(cs_path), "--receipts", str(rr_path), "--validate-only"])
        assert rc == 0


def test_validate_only_rejects_unlinked_receipt():
    rr_data = {
        "schema_version": 1,
        "receipt_id": "rcpt_orphan",
        "change_id": "chg_nonexistent",
        "trace_id": {"state": "known", "value": "t1", "source": "test"},
        "rollback_group_id": {"state": "known", "value": "grp", "source": "test"},
        "sequence_index": 0,
        "parent_receipt_id": {"state": "not_applicable", "value": None, "reason": "first", "source": "test"},
        "depends_on_receipt_ids": [],
        "rollback_kind": "git_revert",
        "rollback_target": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "x", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "outcome": "succeeded",
        "observed_pre_rollback": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "new", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "observed_post_rollback": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}},
        "confirmation": {"status": "confirmed", "expected": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}}, "observed": {"object_type": "file", "scope": "repo", "locator": {"state": "known", "value": "old", "source": "test"}, "hash_algorithm": "unknown", "digest": {"state": "unknown", "value": None, "reason": "test", "source": "test"}, "size_bytes": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}, "version_ref": {"state": "not_applicable", "value": None, "reason": "test", "source": "test"}}, "verifier": {"state": "known", "value": "v", "source": "test"}, "compared_fields": ["object_type", "scope", "digest"], "mismatches": []},
        "revision": {"state": "known", "value": "r1", "source": "test"},
        "config_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "policy_fingerprint": {"state": "unknown", "value": None, "reason": "test", "source": "test"},
        "evidence_refs": [],
        "source_event_ids": [],
        "provenance": {"origin": "persisted", "derivation_rule": None, "source_ids": [], "confidence": "exact"},
        "unknowns": [],
        "attempted_at": {"state": "known", "value": 1000.0, "source": "test"},
        "confirmed_at": {"state": "known", "value": 1010.0, "source": "test"},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        cs_path = Path(tmpdir) / "changes.json"
        rr_path = Path(tmpdir) / "receipts.json"
        _write_json(cs_path, [])
        _write_json(rr_path, [rr_data])
        rc = main(["--changes", str(cs_path), "--receipts", str(rr_path), "--validate-only"])
        assert rc != 0
