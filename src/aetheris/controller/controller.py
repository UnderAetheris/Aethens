from __future__ import annotations
from dataclasses import dataclass

from ..config import Config
from ..memory.store import MemoryStore
from ..safety.guard import ActionRequest, SafetyLayer
from ..tools.base import ToolRegistry
from ..tools.builtins import default_registry


@dataclass
class TaskResult:
    ok: bool
    output: str


class Controller:
    """Receives a task and routes it. v0.1 routes everything through the echo tool,
    but every tool call now passes through the SafetyLayer first."""

    def __init__(
        self,
        config: Config,
        registry: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
        safety: SafetyLayer | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or default_registry()
        self.memory = memory or MemoryStore(config.log_path)
        self.safety = safety or SafetyLayer(self.memory, safe_mode=config.safe_mode)

    def handle(self, task: str, dry_run: bool = False) -> TaskResult:
        self.memory.record("task_received", {"task": task})

        tool = self.registry.get("echo")  # planner will choose the tool later
        request = ActionRequest(
            tool=tool.name, arg=task, safe=tool.safe, dry_run=dry_run
        )
        action = self.safety.run(tool, request)

        if not action.allowed:
            self.memory.record("task_blocked", {"task": task, "reason": action.reason})
            return TaskResult(ok=False, output=f"blocked: {action.reason}")

        output = action.output if action.executed else (action.preview or "")
        self.memory.record("task_completed", {"task": task, "output": output})
        return TaskResult(ok=True, output=output)
