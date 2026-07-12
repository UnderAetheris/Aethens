from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..memory import ExperienceMemory
from .plan import MultiStepPlan, PlanStep

if TYPE_CHECKING:
    from ..model import ModelProvider
    from ..skills.registry import SkillRegistry


@dataclass(frozen=True)
class Plan:
    """A planner's single-step decision (v1 contract, unchanged)."""

    tool: str
    arg: str
    reason: str
    confident: bool = True


_PATH_RE = re.compile(r"path=(\S+)")
_CONTENT_RE = re.compile(r"content=(.*)$", re.DOTALL)
_WRITE_VERBS = ("write", "create", "save")
_READ_VERBS = ("read", "open", "show", "cat")
_LIST_VERBS = ("list", "ls", "dir")

# Connectors that signal sequential intent in a multi-step task.
_STEP_SPLIT_RE = re.compile(r"\s+(?:and\s+then|then)\s+", re.IGNORECASE)


class Planner:
    """Deterministic, rule-based planner. First matching rule wins.

    `extra_keywords` augments the built-in verb lists per intent. It is the
    ONLY surface the learning engine may modify, and changes are fully
    reversible (add/remove a keyword).
    """

    def __init__(
        self,
        extra_keywords: dict[str, list[str]] | None = None,
        learned_store_path: str | None = None,
        model: ModelProvider | None = None,
        registry_tools: tuple[str, ...] | None = None,
        skills: SkillRegistry | None = None,
        experience: ExperienceMemory | None = None,
    ) -> None:
        loaded: dict[str, list[str]] = {}
        if learned_store_path is not None:
            from ..memory.learned import LearnedKeywordStore

            loaded = LearnedKeywordStore(learned_store_path).as_keywords()

        merged: dict[str, list[str]] = {k: list(v) for k, v in loaded.items()}
        for intent, words in (extra_keywords or {}).items():
            bucket = merged.setdefault(intent, [])
            for word in words:
                if word not in bucket:
                    bucket.append(word)
        self._extra = merged
        self._model = model
        self._registry_tools = registry_tools or ()
        self._skills = skills  # None → skill recognition disabled (byte-for-byte fallback)
        self._experience = experience  # None → no experience-guided re-ranking

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

        # 5. Default: chat-style input; try model if available, else echo with confidence.
        if self._model is not None and self._registry_tools:
            return self._fallback(task, "no tool intent detected; try model")
        return Plan("echo", text, "no tool intent detected; default echo")

    def _fallback(self, task: str, why: str) -> Plan:
        """Try the model for a suggestion; fall back to deterministic echo if it fails.
        
        This is called when either:
        - A rule matched but required arguments are missing, OR
        - No rule matched and we have a model to consult
        
        Returns a Plan marked as not confident, since the model output or fallback
        was chosen due to incomplete/missing information.
        """
        # Try model first if available and it has tool knowledge
        if self._model is not None and self._registry_tools:
            try:
                from ..model import ModelRequest, ResponseKind

                req = ModelRequest(
                    kind=ResponseKind.PLAN_SUGGESTION,
                    task=task,
                    tool_names=self._registry_tools,
                )
                resp = self._model.complete(req)
                validated = self._validate_suggestion(resp)
                if validated is not None:
                    return validated
            except Exception:
                pass

        # Safe fallback: echo the raw task, flagged as not confident.
        return Plan("echo", task.strip(), f"fallback: {why}", confident=False)

    def _validate_suggestion(self, resp) -> Plan | None:  # type: ignore
        """Validate a model response before trusting it as a plan.
        
        Returns a Plan if the suggestion is valid, None if invalid (tool unknown,
        arg malformed, response failed, etc.).
        """
        if not resp.ok or resp.suggestion is None:
            return None  # abstained or failed

        tool = resp.suggestion.get("tool")
        arg = resp.suggestion.get("arg")

        # Tool must exist in registry
        if tool not in self._registry_tools:
            return None

        # Arg must be serializable to valid JSON
        try:
            arg_str = json.dumps(arg) if not isinstance(arg, str) else arg
            json.loads(arg_str)  # validate JSON shape
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        # All checks passed -> return a plan from the suggestion
        return Plan(
            tool=tool,
            arg=arg_str,
            reason=f"model suggestion ({resp.provider})",
            confident=False,
        )

    # ------------------------------------------------------------------ #
    # Multi-step planning (v2)                                            #
    # ------------------------------------------------------------------ #

    def plan_multi(self, task: str, task_id: str) -> MultiStepPlan:
        """Decompose a task into a MultiStepPlan.

        Skill-match runs first (deterministic, conservative):
        - Confident match + successful param bind + valid render → use skill.
        - No match or missing params → fall back to normal decomposition.
        Normal decomposition is byte-for-byte unchanged.
        """
        plan_source = "decomposed"

        # Skill recognition: check in front of normal planning.
        if self._skills is not None:
            matched = self._skills.match(task, experience=self._experience)
            if matched is not None:
                skill, params = matched
                try:
                    plan = skill.render(task_id, params)
                    plan.plan_source = f"skill:{skill.name}@v{skill.version}"
                    # Validate: every tool in the rendered plan must exist in the registry.
                    if self._registry_tools:
                        for step in plan.steps:
                            if step.tool not in self._registry_tools:
                                raise ValueError(f"unknown tool '{step.tool}' in skill '{skill.name}'")
                    return plan
                except Exception:
                    plan_source = "fallback:invalid_render"
            else:
                plan_source = self._skill_fallback_reason(task)

        # Normal decomposition (unchanged).
        fragments = _STEP_SPLIT_RE.split(task.strip())

        if len(fragments) > 1:
            steps: list[PlanStep] = []
            for i, fragment in enumerate(fragments):
                single = self.plan(fragment.strip())
                if not single.confident:
                    # Can't confidently plan this fragment — fall back to
                    # a single-step plan for the whole task.
                    return self._single_step_plan(task, task_id, plan_source)
                steps.append(
                    PlanStep(
                        tool=single.tool,
                        arg=single.arg,
                        reason=single.reason,
                        depends_on=[i - 1] if i > 0 else [],
                    )
                )
            plan = MultiStepPlan(task_id=task_id, steps=steps)
            plan.plan_source = plan_source
            return plan

        return self._single_step_plan(task, task_id, plan_source)

    def _skill_fallback_reason(self, task: str) -> str:
        """Determine why no skill matched: no trigger fired or params failed to bind."""
        if self._skills is None:
            return "fallback:no_trigger_match"
        for skill in self._skills.active_skills():
            if skill.matches(task):
                return "fallback:bind_failed"
        return "fallback:no_trigger_match"

    def _single_step_plan(self, task: str, task_id: str, plan_source: str = "decomposed") -> MultiStepPlan:
        """Wrap a single Plan as a one-step MultiStepPlan."""
        single = self.plan(task)
        plan = MultiStepPlan(
            task_id=task_id,
            steps=[
                PlanStep(
                    tool=single.tool,
                    arg=single.arg,
                    reason=single.reason,
                    depends_on=[],
                )
            ],
        )
        plan.plan_source = plan_source
        return plan
