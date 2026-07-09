from __future__ import annotations
from .base import Tool, ToolRegistry


def _echo(text: str) -> str:
    return text


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(name="echo", description="Return the input unchanged.", run=_echo, safe=True)
    )
    return registry
