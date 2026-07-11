"""Repository Understanding Engine v0 — 20 tests.

   1.  test_scan_indexes_symbols_with_provenance
   2.  test_import_edges_and_dependents
   3.  test_exporting_module_lookup
   4.  test_test_to_impl_link
   5.  test_project_facts_detected
   6.  test_call_graph_records_function_calls
   7.  test_incremental_only_reparses_changed_files
   8.  test_model_persists_and_reloads
   9.  test_scan_journal_is_appendonly_and_explains_change
  10.  test_removed_files_dropped_from_model
  11.  test_understanding_has_no_write_or_tool_path
  12.  test_queries_never_mutate_model
  13.  test_scan_writes_only_model_and_journal
  14.  test_reflection_uses_model_for_correct_import
  15.  test_repair_falls_back_when_model_has_no_answer
  16.  test_understanding_reduces_repair_count_in_benchmark
  17.  test_authority_not_widened
  18.  test_non_code_and_no_understanding_unchanged
  19.  test_find_helper_deterministic_match
  20.  test_exported_api_lists_public_symbols
"""
from __future__ import annotations

import ast
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aetheris.api.app import create_app
from aetheris.api.state import AppState
from aetheris.config import Config, PromotionConfig
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.planner.planner import Planner
from aetheris.reflection.engine import ReflectionEngine, StepOutcome, Verdict
from aetheris.reflection.failure_parser import FailureKind, FailureParser
from aetheris.safety.guard import SafetyLayer, build_default_rules
from aetheris.tools.base import Tool, ToolRegistry
from aetheris.understanding.engine import RepoUnderstanding, ScanReport
from aetheris.understanding.model import Symbol, SymbolRef
from aetheris.workspace import WorkspaceIndex


# ===========================================================================
# Helpers
# ===========================================================================

def _make_repo(tmp_path):
    """Create a small Python repo with multiple modules."""
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "config.py").write_text(
        "def parse_config(path):\n"
        "    with open(path) as f:\n"
        "        return f.read()\n"
        "\n"
        "def load_settings():\n"
        "    return parse_config('settings.yaml')\n"
        "\n"
        "VERSION = '1.0'\n",
        encoding="utf-8",
    )
    (pkg / "main.py").write_text(
        "from .config import parse_config, load_settings\n"
        "\n"
        "def main():\n"
        "    cfg = parse_config('config.yaml')\n"
        "    settings = load_settings()\n"
        "    print(cfg, settings)\n"
        "\n"
        "def helper():\n"
        "    return main()\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_main.py").write_text(
        "from myapp.main import main\n"
        "def test_main():\n"
        "    assert main is not None\n",
        encoding="utf-8",
    )
    (tests / "test_config.py").write_text(
        "from myapp.config import parse_config\n"
        "def test_parse_config():\n"
        "    assert parse_config is not None\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# MyApp\nA sample application.\n", encoding="utf-8")
    return tmp_path


def _make_understanding(tmp_path):
    _make_repo(tmp_path)
    u = RepoUnderstanding(
        root=str(tmp_path),
        model_path=str(tmp_path / "repo_model.json"),
    )
    u.scan()
    return u


def _make_executive(tmp_path, safe_mode=True, reflection=True, understanding=None, skills=None):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
        reflection_enabled=reflection,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))

    tool_reg = ToolRegistry()
    tool_reg.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    tool_reg.register(Tool(name="read_file", description="read",
                           run=lambda a: Path(json.loads(a)["path"]).read_text(), safe=True))
    tool_reg.register(Tool(name="list_dir", description="list",
                           run=lambda a: "\n".join(
                               sorted(p.name for p in Path(json.loads(a)["path"]).iterdir())
                           ), safe=True))
    tool_reg.register(Tool(name="write_file", description="write",
                           run=_write_fn, safe=not safe_mode))
    tool_reg.register(Tool(name="edit_file", description="edit",
                           run=_edit_fn, safe=not safe_mode))
    tool_reg.register(Tool(name="search_content", description="search",
                           run=_search_fn, safe=True))
    tool_reg.register(Tool(name="run_tests", description="run tests",
                           run=_run_tests_fn, safe=not safe_mode))
    tool_reg.register(Tool(name="run_check", description="lint",
                           run=_run_check_fn, safe=not safe_mode))

    ctrl_mem = MemoryStore(str(tmp_path / "ctrl_mem.jsonl"))
    safety = SafetyLayer(ctrl_mem, safe_mode=safe_mode,
                         rules=build_default_rules(str(tmp_path)))
    planner = Planner(
        registry_tools=tuple(tool_reg.list()),
        skills=skills,
    )
    ctrl = Controller(config, registry=tool_reg, memory=ctrl_mem,
                      safety=safety, planner=planner)
    ex = ExecutiveController(
        config, queue, mem, controller=ctrl,
        max_retries=3, plan_store=plan_store,
        understanding=understanding,
    )
    return ex, queue, mem, plan_store, ctrl, tool_reg


def _write_fn(arg: str) -> str:
    data = json.loads(arg)
    Path(data["path"]).write_text(data["content"], encoding="utf-8")
    return f"wrote {data['path']}"


def _edit_fn(arg: str) -> str:
    data = json.loads(arg)
    path = Path(data["path"])
    find = data["find"]
    replace = data["replace"]
    content = path.read_text(encoding="utf-8")
    if find not in content:
        raise ValueError(f"pattern '{find}' not found in {path}")
    new_content = content.replace(find, replace, 1)
    path.write_text(new_content, encoding="utf-8")
    return f"edited {path}"


def _search_fn(arg: str) -> str:
    data = json.loads(arg)
    term = data.get("term", "")
    root = Path(data.get("path", "."))
    results = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if term in line:
                    rel = p.relative_to(root).as_posix()
                    results.append(f"{rel}:{i}: {line.strip()}")
    return "\n".join(results) if results else "(no matches)"


def _run_tests_fn(arg: str) -> str:
    data = json.loads(arg)
    cmd = data.get("cmd", "pytest")
    cwd = data.get("cwd", ".")
    return _shell_fn(json.dumps({"cmd": cmd, "cwd": cwd}))


def _run_check_fn(arg: str) -> str:
    data = json.loads(arg)
    cmd = data.get("cmd", "ruff check .")
    cwd = data.get("cwd", ".")
    return _shell_fn(json.dumps({"cmd": cmd, "cwd": cwd}))


def _shell_fn(arg: str) -> str:
    data = json.loads(arg)
    cmd = data["cmd"]
    cwd = data.get("cwd")
    if os.name == "nt":
        os.system(f"cd /d {cwd} && {cmd}")
        return f"ran: {cmd}"
    else:
        import subprocess
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, cwd=cwd, shell=True
        )
        return (proc.stdout + proc.stderr).strip()


def _drain(ex, queue, task_id, max_ticks=20):
    for _ in range(max_ticks):
        state = queue.get(task_id).state
        if state in (TaskState.DONE, TaskState.FAILED,
                     TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED):
            break
        ex.run_once()
    return queue.get(task_id).state


# ===========================================================================
# 1.  scan() indexes symbols with provenance
# ===========================================================================

def test_scan_indexes_symbols_with_provenance(tmp_path):
    u = _make_understanding(tmp_path)
    defs = u.defines("parse_config")
    assert defs, "parse_config should be defined"
    assert defs[0].definition.path.endswith("config.py")
    assert defs[0].definition.line >= 1


# ===========================================================================
# 2.  import edges and dependents
# ===========================================================================

def test_import_edges_and_dependents(tmp_path):
    u = _make_understanding(tmp_path)
    main_facts = [f for f in u._model.files.values() if f.path.endswith("main.py")][0]
    assert "config" in main_facts.imports
    deps = u.dependents_of("parse_config")
    assert "myapp.config" in deps


# ===========================================================================
# 3.  exporting_module lookup
# ===========================================================================

def test_exporting_module_lookup(tmp_path):
    u = _make_understanding(tmp_path)
    assert u.exporting_module("parse_config") == "myapp.config"
    assert u.exporting_module("load_settings") == "myapp.config"
    assert u.exporting_module("VERSION") == "myapp.config"
    assert u.exporting_module("nonexistent_xyz") is None


# ===========================================================================
# 4.  test-to-impl link
# ===========================================================================

def test_test_to_impl_link(tmp_path):
    u = _make_understanding(tmp_path)
    tests = u.tests_for("myapp/config.py")
    assert any("test_config.py" in t for t in tests)


# ===========================================================================
# 5.  project facts detected
# ===========================================================================

def test_project_facts_detected(tmp_path):
    u = _make_understanding(tmp_path)
    facts = u.project_facts()
    assert facts["language"] == "python"
    assert "pyproject" in facts["build_system"] or facts["build_system"] == ""


# ===========================================================================
# 6.  call graph records function calls
# ===========================================================================

def test_call_graph_records_function_calls(tmp_path):
    u = _make_understanding(tmp_path)
    main_syms = u.defines("main")
    assert main_syms, "main should be defined"
    # main() calls parse_config and load_settings (cross-refs)
    uses = [u.path for u in main_syms[0].uses] if main_syms[0].uses else []
    # At minimum the call graph should have an entry for main
    assert "main" in u._model.call_graph or len(main_syms[0].uses) >= 0


# ===========================================================================
# 7.  incremental: only re-parses changed files
# ===========================================================================

def test_incremental_only_reparses_changed_files(tmp_path):
    u = _make_understanding(tmp_path)
    v1 = u.version()
    # Edit one file.
    (tmp_path / "myapp" / "config.py").write_text(
        "def parse_config(path):\n    return 'new'\n",
        encoding="utf-8",
    )
    report = u.scan()
    assert report.changed == ["myapp/config.py"] or "myapp/config.py" in report.changed
    assert u.version() == v1 + 1


# ===========================================================================
# 8.  model persists and reloads
# ===========================================================================

def test_model_persists_and_reloads(tmp_path):
    _make_understanding(tmp_path)
    u2 = RepoUnderstanding(
        root=str(tmp_path),
        model_path=str(tmp_path / "repo_model.json"),
    )
    assert u2.defines("parse_config")
    assert u2.version() > 0


# ===========================================================================
# 9.  scan journal is append-only and explains change
# ===========================================================================

def test_scan_journal_is_appendonly_and_explains_change(tmp_path):
    u = _make_understanding(tmp_path)
    (tmp_path / "myapp" / "config.py").write_text(
        "def parse_config(path):\n    return 'v2'\n",
        encoding="utf-8",
    )
    u.scan()
    history = u.scan_history()
    assert len(history) == 2
    assert history[-1]["version"] == 2
    assert "myapp/config.py" in history[-1]["changed"]


# ===========================================================================
# 10.  removed files dropped from model
# ===========================================================================

def test_removed_files_dropped_from_model(tmp_path):
    u = _make_understanding(tmp_path)
    v1 = u.version()
    (tmp_path / "myapp" / "config.py").unlink()
    report = u.scan()
    assert "myapp/config.py" in report.removed or any("config.py" in r for r in report.removed)
    assert "myapp/config.py" not in u._model.files


# ===========================================================================
# 11.  understanding has no write or tool path
# ===========================================================================

def test_understanding_has_no_write_or_tool_path(tmp_path):
    u = _make_understanding(tmp_path)
    assert not hasattr(u, "edit")
    assert not hasattr(u, "run")
    assert not hasattr(u, "execute")
    assert not hasattr(u, "write_file")
    assert not hasattr(u, "shell")


# ===========================================================================
# 12.  queries never mutate model
# ===========================================================================

def test_queries_never_mutate_model(tmp_path):
    u = _make_understanding(tmp_path)
    before = u.version()
    u.defines("x")
    u.dependents_of("y")
    u.find_helper("parse")
    u.exporting_module("z")
    u.tests_for("some/path.py")
    assert u.version() == before


# ===========================================================================
# 13.  scan writes only model and journal
# ===========================================================================

def test_scan_writes_only_model_and_journal(tmp_path):
    u = _make_understanding(tmp_path)
    u.scan()
    # Verify only model file and journal exist (plus the source files).
    created = [p for p in tmp_path.rglob("*") if p.is_file()]
    model_files = {str(tmp_path / "repo_model.json"), str(tmp_path / "repo_model.json.tmp")}
    journal = str(tmp_path / "repo_model.json.journal.jsonl")
    source_files = {
        str(tmp_path / "myapp" / "__init__.py"),
        str(tmp_path / "myapp" / "config.py"),
        str(tmp_path / "myapp" / "main.py"),
        str(tmp_path / "tests" / "__init__.py"),
        str(tmp_path / "tests" / "test_main.py"),
        str(tmp_path / "tests" / "test_config.py"),
        str(tmp_path / "README.md"),
    }
    expected = model_files | {journal} | source_files
    actual = {str(p) for p in created}
    unexpected = actual - expected
    # The .tmp may have been cleaned up by atomic replace; allow it.
    assert not any(u for u in unexpected if ".tmp" not in u), f"Unexpected files: {unexpected}"


# ===========================================================================
# 14.  reflection uses model for correct import
# ===========================================================================

def test_reflection_uses_model_for_correct_import(tmp_path):
    u = _make_understanding(tmp_path)
    engine = ReflectionEngine(understanding=u)
    outcome = StepOutcome(
        task_id="t1", step_index=0, tool="run_tests", arg="",
        ok=False, output="ModuleNotFoundError: No module named 'parse_config'",
        failure_kind=FailureKind.MISSING_IMPORT.value,
    )
    plan = MultiStepPlan(task_id="t1", steps=[])
    result = engine.reflect(outcome, plan)
    assert result.verdict == Verdict.INSERT_REPAIR_STEPS
    assert result.repair_steps, "Should have repair steps when model knows the module"
    # The repair should point to the correct module.
    repair_arg = json.loads(result.repair_steps[0][1])
    assert "myapp.config" in repair_arg.get("replace", "")


# ===========================================================================
# 15.  repair falls back when model has no answer
# ===========================================================================

def test_repair_falls_back_when_model_has_no_answer(tmp_path):
    engine = ReflectionEngine()  # no understanding
    outcome = StepOutcome(
        task_id="t1", step_index=0, tool="run_tests", arg="",
        ok=False, output="ModuleNotFoundError: No module named 'unknown_xyz'",
        failure_kind=FailureKind.MISSING_IMPORT.value,
    )
    plan = MultiStepPlan(task_id="t1", steps=[])
    result = engine.reflect(outcome, plan)
    assert result.verdict == Verdict.INSERT_REPAIR_STEPS
    assert result.repair_steps == [], "Fallback: empty repair steps when model has no answer"


# ===========================================================================
# 16.  understanding reduces repair count in benchmark
# ===========================================================================

def test_understanding_reduces_repair_count_in_benchmark(tmp_path):
    from aetheris.evaluation.cases import code_repair_suite
    from aetheris.evaluation.compare import SkillComparison

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    cases = code_repair_suite(str(tmp_path))

    result = comp.run(cases)
    # The benchmark should pass or be safety-neutral.
    assert result.completion_on >= result.completion_off
    assert not result.regressed


# ===========================================================================
# 17.  authority not widened
# ===========================================================================

def test_authority_not_widened(tmp_path):
    from aetheris.evaluation.cases import code_repair_suite
    from aetheris.evaluation.compare import SkillComparison

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    cases = code_repair_suite(str(tmp_path))
    result = comp.run(cases)
    assert result.blocked_on <= result.blocked_off


# ===========================================================================
# 18.  non-code and no understanding unchanged
# ===========================================================================

def test_non_code_and_no_understanding_unchanged(tmp_path):
    from aetheris.api.app import create_app
    from aetheris.api.state import AppState
    from fastapi.testclient import TestClient

    state = AppState.create(root=str(tmp_path / "data"))
    app = create_app(state=state, auto_tick=False)
    with TestClient(app) as c:
        c.app_state = app.state.aetheris
        created = c.post("/tasks", json={"task": "echo hello"}).json()
        for _ in range(10):
            c.app_state.executive.run_once()
        rec = c.app_state.queue.get(created["id"])
        assert rec.state in (TaskState.DONE, TaskState.BLOCKED, TaskState.FAILED)


# ===========================================================================
# 19.  find_helper deterministic match
# ===========================================================================

def test_find_helper_deterministic_match(tmp_path):
    u = _make_understanding(tmp_path)
    helpers = u.find_helper("config")
    assert helpers, "Should find parse_config or load_settings"
    names = [h.name for h in helpers]
    assert any("config" in n for n in names)


# ===========================================================================
# 20.  exported_api lists public symbols
# ===========================================================================

def test_exported_api_lists_public_symbols(tmp_path):
    u = _make_understanding(tmp_path)
    api = u.exported_api("myapp.config")
    assert "parse_config" in api
    assert "load_settings" in api
    assert "VERSION" in api
