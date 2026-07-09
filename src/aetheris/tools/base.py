from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    run: Callable[[str], str]
    safe: bool = True
    undo: Callable[[str], None] | None = None  # reversibility hook (optional)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list(self) -> list[str]:
        return sorted(self._tools)
