import json

from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.planner.planner import Planner


def test_chat_task_plans_echo():
    plan = Planner().plan("hello there, how are you")
    assert plan.tool == "echo" and plan.confident


def test_read_task_plans_read_file():
    plan = Planner().plan("read the file at path=/tmp/notes.txt")
    assert plan.tool == "read_file"
    assert json.loads(plan.arg)["path"] == "/tmp/notes.txt"


def test_list_task_plans_list_dir():
    plan = Planner().plan("list path=/tmp")
    assert plan.tool == "list_dir"
    assert json.loads(plan.arg)["path"] == "/tmp"


def test_write_task_plans_write_file():
    plan = Planner().plan("create path=/tmp/out.txt content=hello world")
    assert plan.tool == "write_file"
    data = json.loads(plan.arg)
    assert data["path"] == "/tmp/out.txt" and data["content"] == "hello world"


def test_shell_task_plans_shell_on_explicit_prefix():
    plan = Planner().plan("run: echo hi")
    assert plan.tool == "shell"
    assert json.loads(plan.arg)["cmd"] == "echo hi"


def test_ambiguous_write_falls_back_to_echo():
    plan = Planner().plan("please save this somewhere")
    assert plan.tool == "echo" and not plan.confident
    assert "fallback" in plan.reason


def test_ambiguous_read_falls_back_to_echo():
    plan = Planner().plan("open the file for me")
    assert plan.tool == "echo" and not plan.confident


def test_controller_uses_planner_and_logs_plan(tmp_path):
    controller = Controller(Config(log_path=str(tmp_path / "mem.jsonl")))
    result = controller.handle("just saying hi")
    assert result.ok and result.output == "just saying hi"
    kinds = [e["kind"] for e in controller.memory.history()]
    assert "plan_selected" in kinds
    assert kinds.index("plan_selected") < kinds.index("task_completed")


def test_controller_read_end_to_end_in_safe_mode(tmp_path):
    target = tmp_path / "n.txt"
    target.write_text("data here")
    controller = Controller(
        Config(log_path=str(tmp_path / "mem.jsonl"), workspace_root=str(tmp_path))
    )
    result = controller.handle(f"read path={target}")
    assert result.ok and result.output == "data here"


def test_controller_logs_uncertainty_for_ambiguous(tmp_path):
    controller = Controller(Config(log_path=str(tmp_path / "mem.jsonl")))
    controller.handle("save this please")
    assert "plan_uncertain" in [e["kind"] for e in controller.memory.history()]
