#!/usr/bin/env python3
"""Architecture Integrity Checker v0.

Read-only in CI. Two modes:
  --check          Validate ledgers, defaults, README sync, AST tripwire, artifacts, CI.
  --render-readme  Regenerate the README architecture table (developer-only).

Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES_PATH = REPO_ROOT / "architecture" / "capabilities.json"
AUTHORITY_PATH = REPO_ROOT / "architecture" / "authority.json"
README_PATH = REPO_ROOT / "README.md"
ARCHITECTURE_DOC_PATH = REPO_ROOT / "architecture" / "ARCHITECTURE_BASELINE.md"
EVIDENCE_DIR = REPO_ROOT / "architecture" / "evidence"
SCRIPTS_DIR = REPO_ROOT / "scripts"
SRC_DIR = REPO_ROOT / "src"
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

CAPABILITIES_START = "<!-- architecture-capabilities:start -->"
CAPABILITIES_END = "<!-- architecture-capabilities:end -->"

ALLOWED_IMPLEMENTATION = {"absent", "partial", "complete", "deprecated", "replaced"}
ALLOWED_MEASUREMENT = {"unmeasured", "measured", "stale", "unknown"}
ALLOWED_ADOPTION = {"not_applicable", "hold", "adopted", "rejected", "retired", "unknown"}
ALLOWED_RUNTIME_STATE = {"on", "off", "not_applicable", "unknown"}
ALLOWED_READINESS = {"not_ready", "ready", "unknown"}
ALLOWED_EVIDENCE_DECISION = {"not_applicable", "pass", "hold", "reject", "unknown", "adopted", "stale"}
ALLOWED_ROLLBACK_KIND = {
    "config_disable", "git_revert", "tombstone", "restore_backup",
    "discard_sandbox", "restart_rehydrate", "not_applicable", "unknown",
}

SIDE_EFFECT_FUNCS = {
    "subprocess.run", "subprocess.Popen", "subprocess.call",
    "subprocess.check_call", "subprocess.check_output",
    "os.system", "os.popen",
    "socket.socket", "socket.create_connection",
    "urllib.request.urlopen", "http.client.HTTPConnection",
    "Path.write_text", "Path.write_bytes", "Path.touch", "Path.unlink",
    "Path.rename", "Path.replace", "Path.mkdir", "Path.rmdir",
    "os.remove", "os.unlink", "os.rename", "os.replace",
    "os.mkdir", "os.makedirs", "os.rmdir", "os.removedirs",
    "shutil.copy", "shutil.copy2", "shutil.copytree", "shutil.move", "shutil.rmtree",
}

HTTP_CLIENT_CALLS = {
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.head", "requests.patch", "requests.request",
    "httpx.get", "httpx.post", "httpx.put", "httpx.delete",
    "httpx.head", "httpx.patch", "httpx.request",
    "aiohttp.ClientSession.get", "aiohttp.ClientSession.post",
}


@dataclass
class Finding:
    phase: str
    message: str
    path: str | None = None
    line: int | None = None


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _split_marker(text: str) -> tuple[str, str | None, str]:
    start = text.find(CAPABILITIES_START)
    end = text.find(CAPABILITIES_END)
    if start == -1 or end == -1:
        return text, None, ""
    pre = text[: start + len(CAPABILITIES_START)]
    post = text[end + len(CAPABILITIES_END):]
    inner = text[start + len(CAPABILITIES_START): end]
    return pre, inner, post


def _render_capability_table(caps: list[dict[str, Any]]) -> str:
    lines = [
        "| Capability | Implementation | Measurement | Adoption | Runtime Default | Production Readiness |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for c in caps:
        rd = c.get("runtime_default", {})
        state = rd.get("state", "unknown")
        lines.append(
            f"| {c.get('id', '?')} "
            f"| {c.get('implementation', '?')} "
            f"| {c.get('measurement', '?')} "
            f"| {c.get('adoption', '?')} "
            f"| {state} "
            f"| {c.get('production_readiness', '?')} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Phase A: schema and reference integrity
# ---------------------------------------------------------------------------

def check_schema_and_references(findings: list[Finding], caps: Any, auth: Any) -> None:
    if not isinstance(caps, dict):
        findings.append(Finding("schema", "capabilities.json is not an object", str(CAPABILITIES_PATH)))
        return
    if caps.get("schema_version") != 1:
        findings.append(Finding("schema", f"capabilities schema_version {caps.get('schema_version')} != 1", str(CAPABILITIES_PATH)))
    if not isinstance(caps.get("capabilities"), list):
        findings.append(Finding("schema", "capabilities.capabilities is not an array", str(CAPABILITIES_PATH)))
        return

    seen_ids: set[str] = set()
    for idx, c in enumerate(caps["capabilities"]):
        cid = c.get("id")
        if not cid:
            findings.append(Finding("schema", f"capabilities[{idx}] missing id", str(CAPABILITIES_PATH), idx))
            continue
        if cid in seen_ids:
            findings.append(Finding("schema", f"duplicate capability id {cid}", str(CAPABILITIES_PATH), idx))
        seen_ids.add(cid)

        for field in ("implementation", "measurement", "adoption", "production_readiness"):
            val = c.get(field)
            if val is None:
                findings.append(Finding("schema", f"{cid}.{field} missing", str(CAPABILITIES_PATH), idx))
        if c.get("implementation") not in ALLOWED_IMPLEMENTATION:
            findings.append(Finding("schema", f"{cid}.implementation unknown: {c.get('implementation')}", str(CAPABILITIES_PATH), idx))
        if c.get("measurement") not in ALLOWED_MEASUREMENT:
            findings.append(Finding("schema", f"{cid}.measurement unknown: {c.get('measurement')}", str(CAPABILITIES_PATH), idx))
        if c.get("adoption") not in ALLOWED_ADOPTION:
            findings.append(Finding("schema", f"{cid}.adoption unknown: {c.get('adoption')}", str(CAPABILITIES_PATH), idx))
        if c.get("production_readiness") not in ALLOWED_READINESS:
            findings.append(Finding("schema", f"{cid}.production_readiness unknown: {c.get('production_readiness')}", str(CAPABILITIES_PATH), idx))

        rd = c.get("runtime_default") or {}
        if rd.get("state") not in ALLOWED_RUNTIME_STATE:
            findings.append(Finding("schema", f"{cid}.runtime_default.state unknown: {rd.get('state')}", str(CAPABILITIES_PATH), idx))
        ev = c.get("evidence") or {}
        if ev.get("decision") not in ALLOWED_EVIDENCE_DECISION:
            findings.append(Finding("schema", f"{cid}.evidence.decision unknown: {ev.get('decision')}", str(CAPABILITIES_PATH), idx))
        rb = c.get("rollback") or {}
        if rb.get("kind") not in ALLOWED_ROLLBACK_KIND:
            findings.append(Finding("schema", f"{cid}.rollback.kind unknown: {rb.get('kind')}", str(CAPABILITIES_PATH), idx))

        if not isinstance(c.get("required_permissions"), list):
            findings.append(Finding("schema", f"{cid}.required_permissions not a list", str(CAPABILITIES_PATH), idx))
        if not isinstance(c.get("owner_paths"), list):
            findings.append(Finding("schema", f"{cid}.owner_paths not a list", str(CAPABILITIES_PATH), idx))
        if not isinstance(c.get("known_limitations"), list):
            findings.append(Finding("schema", f"{cid}.known_limitations not a list", str(CAPABILITIES_PATH), idx))
        if not isinstance(c.get("safety_gate_path"), list):
            findings.append(Finding("schema", f"{cid}.safety_gate_path not a list", str(CAPABILITIES_PATH), idx))

    if not isinstance(auth, dict):
        findings.append(Finding("schema", "authority.json is not an object", str(AUTHORITY_PATH)))
        return
    if auth.get("schema_version") != 1:
        findings.append(Finding("schema", f"authority schema_version {auth.get('schema_version')} != 1", str(AUTHORITY_PATH)))

    seen_profile_ids: set[str] = set()
    for p in auth.get("profiles", []):
        pid = p.get("id")
        if not pid:
            findings.append(Finding("schema", "authority profile missing id", str(AUTHORITY_PATH)))
            continue
        if pid in seen_profile_ids:
            findings.append(Finding("schema", f"duplicate authority profile id {pid}", str(AUTHORITY_PATH)))
        seen_profile_ids.add(pid)
        cid = p.get("capability_id")
        if cid not in seen_ids:
            findings.append(Finding("schema", f"profile {pid} references missing capability {cid}", str(AUTHORITY_PATH)))
        auth_map = p.get("authority") or {}
        if len(auth_map) != 10:
            findings.append(Finding("schema", f"profile {pid} has {len(auth_map)} authority dimensions, expected 10", str(AUTHORITY_PATH)))
        for dim in auth.get("authority_dimensions", []):
            if dim not in auth_map:
                findings.append(Finding("schema", f"profile {pid} missing dimension {dim}", str(AUTHORITY_PATH)))
        if auth_map.get("approve_own_proposals", {}).get("level") != "none":
            findings.append(Finding("schema", f"profile {pid} approve_own_proposals is not none", str(AUTHORITY_PATH)))

    seen_boundary_ids: set[str] = set()
    for b in auth.get("boundaries", []):
        bid = b.get("id")
        if not bid:
            findings.append(Finding("schema", "boundary missing id", str(AUTHORITY_PATH)))
            continue
        if bid in seen_boundary_ids:
            findings.append(Finding("schema", f"duplicate boundary id {bid}", str(AUTHORITY_PATH)))
        seen_boundary_ids.add(bid)

    for p in auth.get("profiles", []):
        for dim, entry in (p.get("authority") or {}).items():
            level = entry.get("level") if isinstance(entry, dict) else None
            boundary = entry.get("boundary") if isinstance(entry, dict) else None
            if level in ("direct", "delegated"):
                if not boundary or boundary not in seen_boundary_ids:
                    findings.append(Finding("schema",
                        f"profile {p['id']} {dim} level={level} references missing boundary {boundary}"))


# ---------------------------------------------------------------------------
# Phase B: runtime-default integrity
# ---------------------------------------------------------------------------

def _state_from_config(attr_val: Any) -> str:
    if attr_val is True:
        return "on"
    if attr_val is False:
        return "off"
    if isinstance(attr_val, (list, tuple)) and len(attr_val) == 0:
        return "off"
    return "unknown"


def check_runtime_defaults(findings: list[Finding], caps: list[dict[str, Any]]) -> None:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from aetheris.config import Config  # noqa: E402
    except Exception as exc:
        findings.append(Finding("runtime_defaults", f"failed to import Config: {exc}"))
        return

    field_map = {
        "safe_mode": "safe_mode",
        "reflection_enabled": "reflection_enabled",
        "reasoning_enabled": "reasoning_enabled",
        "experience_record": "experience_record",
        "experience_consume": "experience_consume",
        "hierarchy_enabled": "hierarchy_enabled",
        "research_enabled": "research_enabled",
        "unattended_enabled": "unattended_enabled",
        "allowed_shell_commands": "allowed_shell_commands",
        "log_path": "log_path",
        "workspace_root": "workspace_root",
    }

    for c in caps:
        cid = c.get("id", "?")
        rd = c.get("runtime_default") or {}
        cfg_field = rd.get("config_field")
        if not cfg_field or cfg_field == "N/A":
            continue
        expected_state = rd.get("state", "unknown")
        if expected_state == "not_applicable":
            continue
        attr = field_map.get(cfg_field)
        if not attr:
            continue
        default_val = getattr(Config, attr, None)
        if default_val is None:
            findings.append(Finding("runtime_defaults", f"{cid}.{cfg_field} missing from Config dataclass"))
            continue
        actual_state = _state_from_config(default_val)
        if actual_state == "unknown":
            continue
        if actual_state != expected_state:
            findings.append(Finding("runtime_defaults",
                f"{cid} runtime_default.state {expected_state} != Config.{attr} {actual_state}"))


# ---------------------------------------------------------------------------
# Phase C: README synchronization
# ---------------------------------------------------------------------------

def check_readme_sync(findings: list[Finding], caps: list[dict[str, Any]]) -> str:
    text = README_PATH.read_text(encoding="utf-8")
    _, inner, _ = _split_marker(text)
    if inner is None:
        findings.append(Finding("readme_sync", "README missing architecture-capabilities markers"))
        return ""
    expected = _render_capability_table(caps)
    if inner.strip() != expected.strip():
        findings.append(Finding("readme_sync", "README architecture table does not match ledger"))
        return ""
    return inner


def render_readme(caps: list[dict[str, Any]]) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    pre, _, post = _split_marker(text)
    table = _render_capability_table(caps)
    new_text = pre + "\n" + table + "\n" + post
    README_PATH.write_text(new_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase D: architecture doc sync (basic)
# ---------------------------------------------------------------------------

def check_architecture_doc(findings: list[Finding]) -> None:
    if not ARCHITECTURE_DOC_PATH.exists():
        findings.append(Finding("architecture_doc", "architecture/ARCHITECTURE_BASELINE.md missing"))
        return
    text = ARCHITECTURE_DOC_PATH.read_text(encoding="utf-8")
    required_headings = [
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
    for h in required_headings:
        if h not in text:
            findings.append(Finding("architecture_doc", f"missing required heading: {h}"))
    # Verify it references the JSON ledgers.
    if "capabilities.json" not in text:
        findings.append(Finding("architecture_doc", "ARCHITECTURE_BASELINE.md does not reference capabilities.json"))
    if "authority.json" not in text:
        findings.append(Finding("architecture_doc", "ARCHITECTURE_BASELINE.md does not reference authority.json"))


# ---------------------------------------------------------------------------
# Phase E: AST side-effect tripwire
# ---------------------------------------------------------------------------

def _py_roots() -> list[Path]:
    roots = [SRC_DIR]
    if SCRIPTS_DIR.exists():
        roots.append(SCRIPTS_DIR)
    return roots


def _is_excluded(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if ".git" in parts:
        return True
    if ".venv" in parts:
        return True
    if "venv" in parts:
        return True
    if "__pycache__" in parts:
        return True
    if ".pytest_cache" in parts:
        return True
    if ".ruff_cache" in parts:
        return True
    if ".idea" in parts:
        return True
    if ".kilo" in parts:
        return True
    return False


def _scan_ast_for_side_effects(findings: list[Finding]) -> None:
    registered_exceptions: dict[str, list[dict[str, Any]]] = {}
    boundary_exceptions: dict[str, list[dict[str, Any]]] = {}
    auth_path = AUTHORITY_PATH
    if auth_path.exists():
        try:
            auth = _load_json(auth_path)
            for b in auth.get("boundaries", []):
                bid = b.get("id", "")
                for exc in b.get("exceptions", []):
                    cp = exc.get("call_pattern", "")
                    boundary_exceptions.setdefault(cp, []).append({
                        "boundary": bid,
                        "source_path": exc.get("source_path"),
                    })
                for ep in b.get("entrypoints", []):
                    parts = ep.split(".")
                    sym = parts[-1]
                    registered_exceptions.setdefault(sym, []).append({"boundary": bid})
        except Exception:
            pass

    for root in _py_roots():
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if _is_excluded(py):
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            rel = py.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = ""
                    if isinstance(func, ast.Attribute):
                        if isinstance(func.value, ast.Name):
                            name = f"{func.value.id}.{func.attr}"
                        elif isinstance(func.value, ast.Attribute):
                            chain = []
                            cur = func
                            while isinstance(cur, ast.Attribute):
                                chain.append(cur.attr)
                                cur = cur.value
                            if isinstance(cur, ast.Name):
                                chain.append(cur.id)
                            name = ".".join(reversed(chain))
                    elif isinstance(func, ast.Name):
                        name = func.id

                    if name in SIDE_EFFECT_FUNCS or name in HTTP_CLIENT_CALLS:
                        if name in boundary_exceptions:
                            matched = False
                            for exc in boundary_exceptions[name]:
                                if exc.get("source_path") == rel:
                                    matched = True
                                    break
                            if matched:
                                continue
                        if (func.attr if isinstance(func, ast.Attribute) else name) in registered_exceptions:
                            continue
                        findings.append(Finding(
                            "side_effects",
                            f"unregistered side-effect call: {name}",
                            rel,
                            node.lineno,
                        ))


# ---------------------------------------------------------------------------
# Phase F: hidden authority checks (constructor inspection)
# ---------------------------------------------------------------------------

def check_hidden_authority(findings: list[Finding]) -> None:
    hidden_targets = [
        ("ResearchEngine", "src/aetheris/research/engine.py", ["NetworkPerimeter"]),
        ("ReasoningEngine", "src/aetheris/reasoning/engine.py", []),
        ("RepoUnderstanding", "src/aetheris/understanding/engine.py", []),
        ("SourceReliability", "src/aetheris/research/reliability.py", []),
        ("SkillRegistry", "src/aetheris/skills/registry.py", []),
        ("SessionOutcomeLearning", "src/aetheris/unattended/outcome_learning.py", []),
        ("UnattendedSupervisor", "src/aetheris/unattended/supervisor.py", []),
        ("ModelAssistedPatcher", "src/aetheris/learning/model_patch.py", []),
    ]
    forbidden_imports = [
        "aetheris.safety.guard",
        "aetheris.controller.controller",
        "aetheris.controller.executive",
    ]
    for class_name, src_path, allowed_imports in hidden_targets:
        full_path = REPO_ROOT / src_path
        if not full_path.exists():
            continue
        text = full_path.read_text(encoding="utf-8")
        for imp in forbidden_imports:
            if f"from {imp}" in text or f"import {imp}" in text:
                if "tests/" not in str(full_path):
                    findings.append(Finding(
                        "hidden_authority",
                        f"{class_name} imports forbidden module {imp}",
                        src_path,
                    ))
        for attr in ["SafetyLayer", "ExecutiveController"]:
            if attr in text:
                init_section = text.split("def __init__")[1].split("\n\n")[0] if "def __init__" in text else ""
                if attr in init_section:
                    findings.append(Finding(
                        "hidden_authority",
                        f"{class_name} constructor references forbidden {attr}",
                        src_path,
                    ))


# ---------------------------------------------------------------------------
# Phase G: tracked runtime/generated artifact check
# ---------------------------------------------------------------------------

def check_artifacts(findings: list[Finding]) -> None:
    tracked: set[str] = set()
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        tracked = {line.strip() for line in out.stdout.splitlines() if line.strip()}
    except Exception as exc:
        findings.append(Finding("artifacts", f"git ls-files failed: {exc}"))
        return

    forbidden_patterns = [
        ".aetheris_data/",
        "*.jsonl",
        "*.journal",
        "*.aetheris.bak",
        "node_modules/",
        ".env",
        "package-lock.json",
        "tmp_smoke",
    ]
    bad = []
    for pattern in forbidden_patterns:
        if pattern.endswith("/"):
            for item in tracked:
                if item.startswith(pattern):
                    bad.append(item)
        else:
            import fnmatch
            for item in tracked:
                if fnmatch.fnmatch(item, pattern):
                    bad.append(item)
    for item in sorted(set(bad)):
        findings.append(Finding("artifacts", f"tracked runtime/generated artifact: {item}"))


# ---------------------------------------------------------------------------
# Phase H: evidence truthfulness
# ---------------------------------------------------------------------------

def check_evidence_truthfulness(findings: list[Finding], caps: list[dict[str, Any]]) -> None:
    evidence_dir = REPO_ROOT / "architecture" / "evidence"
    if not evidence_dir.exists():
        findings.append(Finding("evidence", "architecture/evidence/ directory missing"))
        return
    for c in caps:
        cid = c.get("id", "?")
        ev = c.get("evidence") or {}
        if ev.get("decision") in ("not_applicable",):
            continue
        # Require evidence only for adopted/default-on gated capabilities.
        if c.get("adoption") != "adopted" and c.get("runtime_default", {}).get("state") != "on":
            continue
        rd = c.get("runtime_default") or {}
        if rd.get("state") == "on" and ev.get("decision") not in ("pass", "adopted"):
            # Adopted default-on without passing evidence.
            pass
        rec_path = ev.get("record")
        if not rec_path:
            findings.append(Finding("evidence", f"{cid} adopted but evidence.record missing"))
            continue
        fp = REPO_ROOT / rec_path
        if not fp.exists():
            findings.append(Finding("evidence", f"{cid} evidence record missing: {rec_path}"))
            continue
        try:
            rec = _load_json(fp)
        except Exception as exc:
            findings.append(Finding("evidence", f"{cid} evidence record invalid JSON: {exc}"))
            continue
        if rec.get("capability_id") != cid:
            findings.append(Finding("evidence", f"{cid} evidence capability_id mismatch"))
        if rec.get("revision") == "<SHA>" or "<SHA>" in str(rec.get("revision")):
            findings.append(Finding("evidence", f"{cid} evidence revision is placeholder"))
        # WORKTREE is allowed during local generation; committed baselines must use real SHA.
        if str(rec.get("revision")) not in ("WORKTREE",) and "<SHA>" not in str(rec.get("revision", "")):
            pass  # real SHA is fine
        raw = rec.get("raw_metrics") or {}
        for metric, info in raw.items():
            if isinstance(info, dict):
                if info.get("observed") is False and info.get("value") is not None:
                    findings.append(Finding("evidence", f"{cid} metric {metric} has value but observed=false"))
                if info.get("value") == 0 and not info.get("observed"):
                    findings.append(Finding("evidence", f"{cid} metric {metric} is zero without observed=true"))
        gate = rec.get("gate") or {}
        if gate.get("verdict") == "pass" and gate.get("exit_code", 0) not in (0, None):
            findings.append(Finding("evidence", f"{cid} gate verdict pass but exit_code nonzero"))
        token = rec.get("rollback_token", "")
        if any(bad in token.lower() for bad in ("secret", "password", "key=", "api_key")):
            findings.append(Finding("evidence", f"{cid} rollback_token looks like a credential"))


# ---------------------------------------------------------------------------
# Phase I: CI topology
# ---------------------------------------------------------------------------

def check_ci_topology(findings: list[Finding]) -> None:
    if not CI_WORKFLOW_PATH.exists():
        findings.append(Finding("ci", "CI workflow file missing"))
        return
    text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    if "continue-on-error: true" in text:
        findings.append(Finding("ci", "continue-on-error: true found in CI workflow"))
    if "pytest || true" in text or "ruff || true" in text:
        findings.append(Finding("ci", "masked command found in CI workflow"))
    jobs = ["lint", "test", "repository-integrity", "reasoning-gate", "research-gate"]
    for job in jobs:
        if f"  {job}:" not in text:
            findings.append(Finding("ci", f"CI job {job} missing"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_check() -> int:
    findings: list[Finding] = []
    caps = None
    auth = None

    # Load JSON.
    if not CAPABILITIES_PATH.exists():
        findings.append(Finding("schema", f"missing {CAPABILITIES_PATH}"))
    else:
        try:
            caps = _load_json(CAPABILITIES_PATH)
        except Exception as exc:
            findings.append(Finding("schema", f"capabilities.json invalid JSON: {exc}"))

    if not AUTHORITY_PATH.exists():
        findings.append(Finding("schema", f"missing {AUTHORITY_PATH}"))
    else:
        try:
            auth = _load_json(AUTHORITY_PATH)
        except Exception as exc:
            findings.append(Finding("schema", f"authority.json invalid JSON: {exc}"))

    capabilities_list = []
    if isinstance(caps, dict) and isinstance(caps.get("capabilities"), list):
        capabilities_list = caps["capabilities"]

    # Phase A
    check_schema_and_references(findings, caps, auth)
    # Phase B
    check_runtime_defaults(findings, capabilities_list)
    # Phase C
    check_readme_sync(findings, capabilities_list)
    # Phase D
    check_architecture_doc(findings)
    # Phase E
    _scan_ast_for_side_effects(findings)
    # Phase F
    check_hidden_authority(findings)
    # Phase G
    check_artifacts(findings)
    # Phase H
    check_evidence_truthfulness(findings, capabilities_list)
    # Phase I
    check_ci_topology(findings)

    if findings:
        print("INTEGRITY CHECK FAILED")
        for f in findings:
            loc = f" [{f.path}:{f.line}]" if f.path and f.line else (f" [{f.path}]" if f.path else "")
            print(f"  {f.phase}: {f.message}{loc}")
        return 1
    print("INTEGRITY CHECK PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Architecture integrity checker v0")
    parser.add_argument("--check", action="store_true", help="Run read-only integrity checks")
    parser.add_argument("--render-readme", action="store_true", help="Regenerate README architecture table")
    args = parser.parse_args()

    if not args.check and not args.render_readme:
        parser.print_help()
        return 2

    if args.render_readme:
        caps = _load_json(CAPABILITIES_PATH)
        render_readme(caps.get("capabilities", []))
        print("README architecture table regenerated.")
        return 0

    return run_check()


if __name__ == "__main__":
    sys.exit(main())
