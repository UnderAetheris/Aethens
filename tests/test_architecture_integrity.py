"""Tests for architecture integrity checker v0.

Covers ledger/schema, runtime defaults, evidence, documentation,
side-effects, artifacts, CI topology, and behavioral neutrality.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES = REPO_ROOT / "architecture" / "capabilities.json"
AUTHORITY = REPO_ROOT / "architecture" / "authority.json"
README = REPO_ROOT / "README.md"
ARCH_DOC = REPO_ROOT / "architecture" / "ARCHITECTURE_BASELINE.md"
CHECKER = REPO_ROOT / "scripts" / "check_architecture_integrity.py"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _run_checker(tmp_caps=None, tmp_authority=None, tmp_readme=None, tmp_arch=None):
    """Run checker with optional temp overrides."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("checker_unique", str(CHECKER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["checker_unique"] = mod
    spec.loader.exec_module(mod)
    if tmp_caps:
        mod.CAPABILITIES_PATH = tmp_caps
    if tmp_authority:
        mod.AUTHORITY_PATH = tmp_authority
    if tmp_readme:
        mod.README_PATH = tmp_readme
    if tmp_arch:
        mod.ARCHITECTURE_DOC_PATH = tmp_arch
    return mod.run_check()


def test_valid_committed_manifests_pass():
    rc = _run_checker()
    assert rc == 0, "committed manifests should pass"


def test_duplicate_capability_id_fails():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = json.loads(CAPABILITIES.read_text())
        data["capabilities"].append(data["capabilities"][0].copy())
        json.dump(data, f)
        f.flush()
        path = Path(f.name)
    try:
        rc = _run_checker(tmp_caps=path)
        assert rc != 0
    finally:
        path.unlink(missing_ok=True)


def test_missing_authority_profile_fails():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = json.loads(AUTHORITY.read_text())
        data["profiles"].append({"id": "ghost", "capability_id": "nonexistent", "authority": {}})
        json.dump(data, f)
        f.flush()
        path = Path(f.name)
    try:
        rc = _run_checker(tmp_authority=path)
        assert rc != 0
    finally:
        path.unlink(missing_ok=True)


def test_unknown_enum_fails():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = json.loads(CAPABILITIES.read_text())
        data["capabilities"][0]["implementation"] = "alien"
        json.dump(data, f)
        f.flush()
        path = Path(f.name)
    try:
        rc = _run_checker(tmp_caps=path)
        assert rc != 0
    finally:
        path.unlink(missing_ok=True)


def test_missing_boundary_reference_fails():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = json.loads(AUTHORITY.read_text())
        data["profiles"][0]["authority"]["reach_network"] = {"level": "direct", "boundary": "network.nonexistent"}
        json.dump(data, f)
        f.flush()
        path = Path(f.name)
    try:
        rc = _run_checker(tmp_authority=path)
        assert rc != 0
    finally:
        path.unlink(missing_ok=True)


def test_complete_does_not_imply_adopted_default_on_ready():
    data = json.loads(CAPABILITIES.read_text())
    for c in data["capabilities"]:
        if c.get("implementation") == "complete":
            # these can be anything else, but the table must not collapse them
            assert "adoption" in c
            assert "runtime_default" in c
            assert "production_readiness" in c


def test_every_capability_has_rollback_and_limitations():
    data = json.loads(CAPABILITIES.read_text())
    for c in data["capabilities"]:
        assert "rollback" in c, f"{c['id']} missing rollback"
        assert "known_limitations" in c, f"{c['id']} missing known_limitations"
        assert isinstance(c["known_limitations"], list)


def test_every_profile_includes_all_ten_dimensions():
    data = json.loads(AUTHORITY.read_text())
    dims = set(data.get("authority_dimensions", []))
    assert dims == {
        "read_files", "write_files", "execute_commands", "reach_network",
        "modify_plans", "modify_memory", "create_skills", "promote_skills",
        "change_config", "approve_own_proposals",
    }
    for p in data.get("profiles", []):
        assert set(p.get("authority", {}).keys()) == dims, f"profile {p['id']} missing dimensions"


def test_approve_own_proposals_is_none_for_all_profiles():
    data = json.loads(AUTHORITY.read_text())
    for p in data.get("profiles", []):
        assert p["authority"]["approve_own_proposals"]["level"] == "none"


def test_every_mapped_config_default_equals_ledger():
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from aetheris.config import Config  # noqa: E402
    caps = json.loads(CAPABILITIES.read_text())["capabilities"]
    field_map = {
        "safe_mode": "safe_mode", "reflection_enabled": "reflection_enabled",
        "reasoning_enabled": "reasoning_enabled", "experience_record": "experience_record",
        "experience_consume": "experience_consume", "hierarchy_enabled": "hierarchy_enabled",
        "research_enabled": "research_enabled", "unattended_enabled": "unattended_enabled",
    }
    for c in caps:
        rd = c.get("runtime_default") or {}
        cfg_field = rd.get("config_field")
        if not cfg_field or cfg_field == "N/A":
            continue
        attr = field_map.get(cfg_field)
        if not attr:
            continue
        val = getattr(Config, attr, None)
        expected = rd.get("state", "unknown")
        if expected == "not_applicable":
            continue
        actual = "on" if val is True else ("off" if val is False else "unknown")
        assert actual == expected, f"{c['id']} config {cfg_field} {actual} != {expected}"


def test_environment_overrides_isolated():
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from aetheris.config import Config  # noqa: E402
    os.environ["AETHERIS_SAFE_MODE"] = "0"
    try:
        cfg = Config.from_env()
        assert cfg.safe_mode is False
    finally:
        del os.environ["AETHERIS_SAFE_MODE"]
    # ensure global is unchanged after call
    cfg2 = Config()
    assert cfg2.safe_mode is True


def test_readme_generated_block_matches_ledger():
    text = README.read_text()
    start = text.find("<!-- architecture-capabilities:start -->")
    end = text.find("<!-- architecture-capabilities:end -->")
    assert start != -1 and end != -1
    inner = text[start + len("<!-- architecture-capabilities:start -->"): end].strip()
    import importlib.util
    spec = importlib.util.spec_from_file_location("checker_table_unique", str(CHECKER))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["checker_table_unique"] = mod
    spec.loader.exec_module(mod)
    expected = mod._render_capability_table(json.loads(CAPABILITIES.read_text())["capabilities"]).strip()
    assert inner == expected


def test_changing_one_ledger_state_without_rendering_readme_fails():
    text = README.read_text()
    end = text.find("<!-- architecture-capabilities:end -->")
    new_text = text[:end] + "| bogus | bogus |\n" + text[end:]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(new_text)
        f.flush()
        path = Path(f.name)
    try:
        rc = _run_checker(tmp_readme=path)
        assert rc != 0
    finally:
        path.unlink(missing_ok=True)


def test_architecture_doc_required_headings_and_boundary_ids():
    text = ARCH_DOC.read_text()
    required = [
        "Purpose and proof boundary",
        "Capability lifecycle definitions",
        "Authority dimensions",
        "Side-effect classes and current owners",
        "Ordinary execution path",
        "Network egress path",
        "Persistence paths",
        "Sandbox validation path",
        "Advisory versus authoritative components",
        "Evidence and adoption contract",
        "Rollback taxonomy",
        "Known unknowns and scanner limitations",
        "How CI enforces the baseline",
        "How to update the baseline without widening authority",
    ]
    for h in required:
        assert h in text, f"missing heading: {h}"
    assert "execution.safety_layer" in text
    assert "network_egress.research_perimeter" in text
    assert "sandbox_validation.model_patch" in text


def test_tracked_runtime_jsonl_fixture_fails():
    fixture = REPO_ROOT / ".aetheris_data" / "test_fixture.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"kind": "runtime", "data": {}}\n')
    try:
        subprocess.run(["git", "add", "-f", str(fixture)], cwd=REPO_ROOT, check=True)
        rc = _run_checker()
        assert rc != 0, "tracked runtime artifact should fail"
    finally:
        subprocess.run(["git", "rm", "-f", str(fixture)], cwd=REPO_ROOT, check=False)
        fixture.unlink(missing_ok=True)


def test_evidence_json_under_approved_dir_passes():
    ev = REPO_ROOT / "architecture" / "evidence" / "test_ok-v0.json"
    data = {
        "schema_version": 1,
        "capability_id": "test_ok",
        "revision": "WORKTREE",
        "recorded_at": "2026-07-22T10:00:00Z",
        "configuration": {},
        "benchmark": {"id": "test", "command": "echo ok", "implementation_paths": []},
        "raw_metrics": {"m": {"value": None, "observed": False, "reason": "n/a"}},
        "gate": {"verdict": "adopted", "exit_code": 0, "output_sha256": "x", "artifact": "test"},
        "rollback_token": "config:disable",
        "limitations": [],
    }
    ev.write_text(json.dumps(data) + "\n")
    try:
        rc = _run_checker()
        assert rc == 0
    finally:
        ev.unlink()


def test_checker_import_safe():
    spec = __import__("importlib.util").util.spec_from_file_location("checker_safe_unique", str(CHECKER))
    mod = __import__("importlib.util").util.module_from_spec(spec)
    sys.modules["checker_safe_unique"] = mod
    spec.loader.exec_module(mod)
    assert hasattr(mod, "run_check")


def test_git_status_neutral_after_check():
    # The checker uses subprocess.run to call git ls-files. Verify it doesn't modify the tree.
    before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True)
    rc = _run_checker()
    after = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert rc == 0 or rc == 1
    assert before.stdout == after.stdout


def test_ci_job_continue_on_error_fails():
    # Temporarily replace CI file with one that has continue-on-error.
    original = CI_WORKFLOW_PATH.read_text()
    bad_ci = original.replace("runs-on: ubuntu-latest", "continue-on-error: true\n    runs-on: ubuntu-latest")
    CI_WORKFLOW_PATH.write_text(bad_ci)
    try:
        rc = _run_checker()
        assert rc != 0
    finally:
        CI_WORKFLOW_PATH.write_text(original)


def test_side_effect_exception_format():
    auth = json.loads(AUTHORITY.read_text())
    for b in auth.get("boundaries", []):
        for exc in b.get("exceptions", []):
            assert "boundary" in exc
            assert "source_path" in exc
            assert "call_pattern" in exc
            assert "reason" in exc
            assert "expected_effect" in exc
            assert "reviewer_owner" in exc
            assert "expiry" in exc


def test_research_engine_allows_network_perimeter():
    text = (REPO_ROOT / "src/aetheris/research/engine.py").read_text()
    assert "NetworkPerimeter" in text


def test_safety_layer_is_single_execution_gate():
    text = (REPO_ROOT / "src/aetheris/safety/guard.py").read_text()
    assert "def run(" in text


def test_no_broad_wildcard_exception():
    auth = json.loads(AUTHORITY.read_text())
    for b in auth.get("boundaries", []):
        for exc in b.get("exceptions", []):
            assert exc.get("call_pattern") != "*", "wildcard exception forbidden"


def test_na_normalized_to_not_applicable():
    caps = json.loads(CAPABILITIES.read_text())["capabilities"]
    for c in caps:
        rd = c.get("runtime_default") or {}
        assert rd.get("config_field") != "N/A", f"{c['id']} has N/A config_field"
        rb = c.get("rollback") or {}
        assert rb.get("token") != "N/A", f"{c['id']} has N/A rollback token"
        assert rb.get("restores") != "N/A", f"{c['id']} has N/A rollback restores"


def test_existing_test_suite_still_passes():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-x"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, f"existing tests regressed: {result.stdout}\n{result.stderr}"


def test_lint_still_passes():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"lint failed: {result.stdout}\n{result.stderr}"
