from __future__ import annotations
from dataclasses import dataclass

from ..config import Config
from ..memory.store import MemoryStore
from ..planner.planner import Planner
from ..safety.guard import ActionRequest, SafetyLayer, build_default_rules
from ..tools.base import ToolRegistry
from ..tools.builtins import default_registry


@dataclass
class TaskResult:
    ok: bool
    output: str


class Controller:
    """Receives a task, asks the planner which tool to run, then routes that
    tool through the SafetyLayer. The planner decides; safety disposes."""

    def __init__(
        self,
        config: Config,
        registry: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        safety: SafetyLayer | None = None,
        planner: Planner | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or default_registry()
        self.memory = memory or MemoryStore(config.log_path)
        self.safety = safety or SafetyLayer(
            self.memory,
            safe_mode=config.safe_mode,
            rules=build_default_rules(
                config.workspace_root, config.allowed_shell_commands
            ),
        )
        self.planner = planner or Planner()

    def handle(self, task: str, dry_run: bool = False) -> TaskResult:
        self.memory.record("task_received", {"task": task})

        plan = self.planner.plan(task)
        self.memory.record(
            "plan_selected",
            {
                "task": task,
                "tool": plan.tool,
                "arg": plan.arg,
                "reason": plan.reason,
                "confident": plan.confident,
            },
        )
        if not plan.confident:
            self.memory.record("plan_uncertain", {"task": task, "reason": plan.reason})

        tool = self.registry.get(plan.tool)
        request = ActionRequest(
            tool=tool.name, arg=plan.arg, safe=tool.safe, dry_run=dry_run
        )
        action = self.safety.run(tool, request)

        if not action.allowed:
            self.memory.record("task_blocked", {"task": task, "reason": action.reason})
            return TaskResult(ok=False, output=f"blocked: {action.reason}")

        output = action.output if action.executed else (action.preview or "")
        self.memory.record("task_completed", {"task": task, "output": output})
        return TaskResult(ok=True, output=output)
