import json

from aetheris.memory.store import MemoryStore
from aetheris.safety.guard import ActionRequest, SafetyLayer, build_default_rules
from aetheris.tools.builtins import default_registry


def _safety(tmp_path, safe_mode):
    mem = MemoryStore(str(tmp_path / "mem.jsonl"))
    rules = build_default_rules(str(tmp_path), ("echo", "ls", "pwd", "cat"))
    return SafetyLayer(mem, safe_mode=safe_mode, rules=rules), mem


def _run(safety, name, arg, **kw):
    reg = default_registry()
    tool = reg.get(name)
    return safety.run(tool, ActionRequest(tool=name, arg=arg, safe=tool.safe, **kw))


def test_read_file_safe_works_in_safe_mode(tmp_path):
    (tmp_path / "hello.txt").write_text("hi there")
    safety, _ = _safety(tmp_path, safe_mode=True)
    result = _run(safety, "read_file", json.dumps({"path": str(tmp_path / "hello.txt")}))
    assert result.executed and result.output == "hi there"


def test_list_dir_safe_works_in_safe_mode(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "b.txt").write_text("")
    safety, _ = _safety(tmp_path, safe_mode=True)
    result = _run(safety, "list_dir", json.dumps({"path": str(tmp_path)}))
    assert result.executed and "a.txt" in result.output and "b.txt" in result.output


def test_write_file_blocked_in_safe_mode(tmp_path):
    safety, mem = _safety(tmp_path, safe_mode=True)
    target = tmp_path / "out.txt"
    result = _run(safety, "write_file", json.dumps({"path": str(target), "content": "x"}))
    assert not result.executed and not result.allowed
    assert not target.exists()
    assert "action_blocked" in [e["kind"] for e in mem.history()]


def test_shell_blocked_in_safe_mode(tmp_path):
    safety, _ = _safety(tmp_path, safe_mode=True)
    result = _run(safety, "shell", json.dumps({"cmd": "echo hi"}))
    assert not result.executed and not result.allowed


def test_write_file_allowed_when_safe_mode_off(tmp_path):
    safety, mem = _safety(tmp_path, safe_mode=False)
    target = tmp_path / "out.txt"
    result = _run(safety, "write_file", json.dumps({"path": str(target), "content": "data"}))
    assert result.executed and target.read_text() == "data"
    assert "action_allowed" in [e["kind"] for e in mem.history()]


def test_shell_allowed_when_safe_mode_off(tmp_path):
    safety, _ = _safety(tmp_path, safe_mode=False)
    result = _run(safety, "shell", json.dumps({"cmd": "echo hi"}))
    assert result.executed and "hi" in result.output


def test_shell_denied_command_blocked_even_when_safe_mode_off(tmp_path):
    safety, _ = _safety(tmp_path, safe_mode=False)
    result = _run(safety, "shell", json.dumps({"cmd": "rm -rf /"}))
    assert not result.executed and "allowlist" in result.reason


def test_path_traversal_blocked_even_when_safe_mode_off(tmp_path):
    safety, _ = _safety(tmp_path, safe_mode=False)
    outside = tmp_path.parent / "secret.txt"
    result = _run(safety, "read_file", json.dumps({"path": str(outside)}))
    assert not result.executed and "escapes" in result.reason


def test_write_file_dry_run_previews_without_writing(tmp_path):
    safety, mem = _safety(tmp_path, safe_mode=False)
    target = tmp_path / "out.txt"
    result = _run(
        safety,
        "write_file",
        json.dumps({"path": str(target), "content": "x"}),
        dry_run=True,
    )
    assert not result.executed and result.allowed and result.preview
    assert not target.exists()
    assert "action_preview" in [e["kind"] for e in mem.history()]


def test_write_file_undo_restores_previous_state(tmp_path):
    safety, _ = _safety(tmp_path, safe_mode=False)
    target = tmp_path / "out.txt"
    target.write_text("original")
    reg = default_registry()
    tool = reg.get("write_file")
    arg = json.dumps({"path": str(target), "content": "changed"})
    safety.run(tool, ActionRequest(tool="write_file", arg=arg, safe=False))
    assert target.read_text() == "changed"
    tool.undo(arg)
    assert target.read_text() == "original"
