from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..memory.store import MemoryStore
from ..tools.base import Tool


@dataclass(frozen=True)
class ActionRequest:
    """A request to run a tool. Everything the safety layer needs to decide."""

    tool: str
    arg: str
    safe: bool = True
    dry_run: bool = False


@dataclass(frozen=True)
class Decision:
    """The verdict for a single action."""

    allowed: bool
    reason: str


@dataclass(frozen=True)
class ActionResult:
    """Outcome of routing an action through the safety layer."""

    executed: bool
    allowed: bool
    reason: str
    output: str | None = None
    preview: str | None = None


# A rule inspects (request, safe_mode) and returns a blocking Decision,
# or None to abstain. Deny wins: the first blocking decision stops execution.
Rule = Callable[[ActionRequest, bool], "Decision | None"]


def _safe_mode_rule(request: ActionRequest, safe_mode: bool) -> Decision | None:
    """With safe_mode on, any tool not explicitly marked safe is blocked."""
    if safe_mode and not request.safe:
        return Decision(
            allowed=False,
            reason=f"safe_mode is on and tool '{request.tool}' is not marked safe",
        )
    return None


def default_rules() -> list[Rule]:
    return [_safe_mode_rule]


class SafetyLayer:
    """The single guard every tool action routes through.

    - Evaluates ordered rules (deny wins).
    - Enforces the safe_mode gate.
    - Logs every attempt (allowed, blocked, or previewed) to memory.
    - Supports dry-run previews without executing.
    """

    def __init__(
        self,
        memory: MemoryStore,
        safe_mode: bool,
        rules: list[Rule] | None = None,
    ) -> None:
        self._memory = memory
        self._safe_mode = safe_mode
        self._rules = rules if rules is not None else default_rules()

    def evaluate(self, request: ActionRequest) -> Decision:
        for rule in self._rules:
            decision = rule(request, self._safe_mode)
            if decision is not None and not decision.allowed:
                return decision
        return Decision(allowed=True, reason="passed all safety rules")

    def run(self, tool: Tool, request: ActionRequest) -> ActionResult:
        decision = self.evaluate(request)

        if not decision.allowed:
            self._log("action_blocked", request, decision)
            return ActionResult(executed=False, allowed=False, reason=decision.reason)

        if request.dry_run:
            preview = f"[dry-run] would call {tool.name}({request.arg!r})"
            self._log("action_preview", request, decision, preview=preview)
            return ActionResult(
                executed=False, allowed=True, reason=decision.reason, preview=preview
            )

        output = tool.run(request.arg)
        self._log("action_allowed", request, decision, output=output)
        return ActionResult(
            executed=True, allowed=True, reason=decision.reason, output=output
        )

    def _log(
        self,
        kind: str,
        request: ActionRequest,
        decision: Decision,
        output: str | None = None,
        preview: str | None = None,
    ) -> None:
        self._memory.record(
            kind,
            {
                "tool": request.tool,
                "arg": request.arg,
                "safe": request.safe,
                "dry_run": request.dry_run,
                "safe_mode": self._safe_mode,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "output": output,
                "preview": preview,
            },
        )
