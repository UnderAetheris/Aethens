from __future__ import annotations
from dataclasses import dataclass

from ..config import Config
from ..memory.store import MemoryStore
from ..tools.base import ToolRegistry
from ..tools.builtins import default_registry


@dataclass
class TaskResult:
    ok: bool
    output: str


class Controller:
    """Receives a task and routes it. v0.1 routes everything through the echo tool."""

    def __init__(
        self,
        config: Config,
        registry: ToolRegistry | None = None,
        memory: MemoryStore | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or default_registry()
        self.memory = memory or MemoryStore(config.log_path)

    def handle(self, task: str) -> TaskResult:
        self.memory.record("task_received", {"task": task})
        tool = self.registry.get("echo")  # planner will choose the tool later
        output = tool.run(task)
        result = TaskResult(ok=True, output=output)
        self.memory.record("task_completed", {"task": task, "output": output})
        return result
