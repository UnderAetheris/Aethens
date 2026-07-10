from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class ResponseKind(str, Enum):
    CHAT = "chat"
    PLAN_SUGGESTION = "plan_suggestion"
    SUMMARY = "summary"
    KNOWLEDGE = "knowledge"
    SKILL_SUGGESTION = "skill_suggestion"


@dataclass(frozen=True)
class ModelRequest:
    """Read-only bundle handed to a provider. No handles to engine state."""

    kind: ResponseKind
    task: str
    context: str = ""
    memory: list[str] = field(default_factory=list)
    tool_names: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    """Structured output. Never an action, only a suggestion/text."""

    kind: ResponseKind
    text: str = ""
    suggestion: dict[str, Any] | None = None
    provider: str = ""
    ok: bool = True


class ModelProvider(Protocol):
    """The whole contract. One method. No tool access, no state mutation."""

    name: str

    def complete(self, request: ModelRequest) -> ModelResponse:
        ...
