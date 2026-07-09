from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.memory.store import MemoryStore
from aetheris.safety.guard import ActionRequest, SafetyLayer
from aetheris.tools.base import Tool, ToolRegistry


def _danger(_: str) -> str:
    return "did something risky"


def _mem(tmp_path):
    return MemoryStore(str(tmp_path / "mem.jsonl"))


def test_safe_tool_allowed_and_logged(tmp_path):
    mem = _mem(tmp_path)
    safety = SafetyLayer(mem, safe_mode=True)
    result = safety.run(
        Tool("echo", "echo", run=lambda s: s, safe=True),
        ActionRequest(tool="echo", arg="hi", safe=True),
    )
    assert result.executed and result.allowed and result.output == "hi"
    assert [e["kind"] for e in mem.history()] == ["action_allowed"]


def test_unsafe_tool_blocked_in_safe_mode(tmp_path):
    mem = _mem(tmp_path)
    safety = SafetyLayer(mem, safe_mode=True)
    result = safety.run(
        Tool("danger", "risky", run=_danger, safe=False),
        ActionRequest(tool="danger", arg="x", safe=False),
    )
    assert not result.executed and not result.allowed
    assert [e["kind"] for e in mem.history()] == ["action_blocked"]


def test_unsafe_tool_allowed_when_safe_mode_off(tmp_path):
    mem = _mem(tmp_path)
    safety = SafetyLayer(mem, safe_mode=False)
    result = safety.run(
        Tool("danger", "risky", run=_danger, safe=False),
        ActionRequest(tool="danger", arg="x", safe=False),
    )
    assert result.executed and result.allowed


def test_dry_run_previews_without_executing(tmp_path):
    mem = _mem(tmp_path)
    calls = []
    tool = Tool("echo", "echo", run=lambda s: calls.append(s) or s, safe=True)
    safety = SafetyLayer(mem, safe_mode=True)
    result = safety.run(tool, ActionRequest(tool="echo", arg="hi", safe=True, dry_run=True))
    assert not result.executed and result.allowed and result.preview
    assert calls == []  # tool never ran
    assert [e["kind"] for e in mem.history()] == ["action_preview"]


def test_controller_blocks_unsafe_tool(tmp_path):
    registry = ToolRegistry()
    registry.register(Tool("echo", "risky echo", run=_danger, safe=False))
    controller = Controller(
        Config(log_path=str(tmp_path / "mem.jsonl"), safe_mode=True),
        registry=registry,
    )
    result = controller.handle("do risky thing")
    assert not result.ok and result.output.startswith("blocked:")
    assert "action_blocked" in [e["kind"] for e in controller.memory.history()]
