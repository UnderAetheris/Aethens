from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    """A planner's decision: which tool to run, with what argument."""

    tool: str
    arg: str
    reason: str
    confident: bool = True


_PATH_RE = re.compile(r"path=(\S+)")
_CONTENT_RE = re.compile(r"content=(.*)$", re.DOTALL)
_WRITE_VERBS = ("write", "create", "save")
_READ_VERBS = ("read", "open", "show", "cat")
_LIST_VERBS = ("list", "ls", "dir")


class Planner:
    """Deterministic, rule-based planner. First matching rule wins.

    `extra_keywords` augments the built-in verb lists per intent. It is the
    ONLY surface the learning engine may modify, and changes are fully
    reversible (add/remove a keyword).
    """

    def __init__(self, extra_keywords: dict[str, list[str]] | None = None) -> None:
        self._extra = extra_keywords or {}

    def _verbs(self, intent: str, base: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(base) + tuple(self._extra.get(intent, []))

    def _contains_verb(self, intent: str, base: tuple[str, ...], text: str) -> bool:
        tokens = re.findall(r"[a-zA-Z]+", text)
        lower_tokens = [token.lower() for token in tokens]
        return any(verb in lower_tokens for verb in self._verbs(intent, base))

    def plan(self, task: str) -> Plan:
        text = task.strip()
        low = text.lower()

        # 1. Explicit shell intent: deliberate prefix only.
        if low.startswith("run:") or text.startswith("$ "):
            cmd = text.split(":", 1)[1].strip() if low.startswith("run:") else text[2:].strip()
            if cmd:
                return Plan("shell", json.dumps({"cmd": cmd}), "explicit shell prefix")
            return self._fallback(task, "shell intent but empty command")

        path_match = _PATH_RE.search(text)

        # 2. Write intent: needs both path= and content=.
        if self._contains_verb("write", _WRITE_VERBS, low):
            content_match = _CONTENT_RE.search(text)
            if path_match and content_match:
                arg = json.dumps(
                    {"path": path_match.group(1), "content": content_match.group(1).strip()}
                )
                return Plan("write_file", arg, "write verb with path and content")
            return self._fallback(task, "write intent but missing path= or content=")

        # 3. List intent: needs path=.
        if self._contains_verb("list", _LIST_VERBS, low):
            if path_match:
                return Plan(
                    "list_dir",
                    json.dumps({"path": path_match.group(1)}),
                    "list verb with path",
                )
            return self._fallback(task, "list intent but missing path=")

        # 4. Read intent: needs path=.
        if self._contains_verb("read", _READ_VERBS, low):
            if path_match:
                return Plan(
                    "read_file",
                    json.dumps({"path": path_match.group(1)}),
                    "read verb with path",
                )
            return self._fallback(task, "read intent but missing path=")

        # 5. Default: chat-style input goes to echo.
        return Plan("echo", text, "no tool intent detected; default echo")

    def _fallback(self, task: str, why: str) -> Plan:
        """Safe fallback: echo the raw task, flagged as not confident."""
        return Plan("echo", task.strip(), f"fallback: {why}", confident=False)
