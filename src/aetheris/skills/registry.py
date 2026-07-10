from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory.jsonl import JsonlStore, make_id
from ..planner.plan import MultiStepPlan, PlanStep


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillStep:
    """One step template inside a skill.

    `arg_template` is a JSON string with `{param}` slots, e.g.
    '{"path": "{path}", "content": "{content}"}'.
    `depends_on` mirrors PlanStep.depends_on (list of step indices).
    """
    tool: str
    arg_template: str
    reason: str
    depends_on: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "arg_template": self.arg_template,
            "reason": self.reason,
            "depends_on": self.depends_on,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillStep":
        return cls(
            tool=d["tool"],
            arg_template=d["arg_template"],
            reason=d["reason"],
            depends_on=d.get("depends_on", []),
        )


@dataclass
class SkillTemplate:
    """A named, versioned, reusable plan template.

    `trigger_patterns` are regex strings; a task matches if any pattern
    matches (case-insensitive).  `required_params` lists the {slot} names
    that must be bound before render() is called.
    """
    id: str
    name: str
    description: str
    trigger_patterns: list[str]
    required_params: list[str]
    steps: list[SkillStep]
    version: int = 1
    created_at: float = field(default_factory=time.time)
    active: bool = True

    # ------------------------------------------------------------------ #
    # Matching                                                             #
    # ------------------------------------------------------------------ #

    def matches(self, task: str) -> bool:
        """Return True if any trigger pattern matches the task (case-insensitive)."""
        low = task.lower()
        return any(re.search(p, low, re.IGNORECASE) for p in self.trigger_patterns)

    def extract_params(self, task: str) -> dict[str, str] | None:
        """Extract required params from the task text.

        Uses the same deterministic extraction the planner already uses:
        `key=value` tokens.  Returns None if any required param is missing.
        """
        params: dict[str, str] = {}
        for param in self.required_params:
            m = re.search(rf"{re.escape(param)}=(\S+)", task)
            if m:
                params[param] = m.group(1)
        if all(p in params for p in self.required_params):
            return params
        return None

    # ------------------------------------------------------------------ #
    # Rendering                                                            #
    # ------------------------------------------------------------------ #

    def render(self, task_id: str, params: dict[str, str]) -> MultiStepPlan:
        """Instantiate the template into a concrete MultiStepPlan.

        Fills `{param}` slots in each step's arg_template.  The result is
        an ordinary MultiStepPlan — indistinguishable from one the planner
        decomposed itself.  From this point the executive, SafetyLayer, and
        Reflection handle it with zero skill-specific logic.
        """
        steps: list[PlanStep] = []
        for tmpl_step in self.steps:
            arg = tmpl_step.arg_template
            for key, val in params.items():
                arg = arg.replace(f"{{{key}}}", val)
            steps.append(PlanStep(
                tool=tmpl_step.tool,
                arg=arg,
                reason=f"[skill:{self.name}] {tmpl_step.reason}",
                depends_on=list(tmpl_step.depends_on),
            ))
        return MultiStepPlan(task_id=task_id, steps=steps)

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "trigger_patterns": self.trigger_patterns,
            "required_params": self.required_params,
            "steps": [s.to_dict() for s in self.steps],
            "version": self.version,
            "created_at": self.created_at,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillTemplate":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            trigger_patterns=d["trigger_patterns"],
            required_params=d["required_params"],
            steps=[SkillStep.from_dict(s) for s in d["steps"]],
            version=d.get("version", 1),
            created_at=d.get("created_at", 0.0),
            active=d.get("active", True),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """JSONL-backed, append-only, versioned skill library.

    Append-only discipline: retiring a skill appends a new record with
    `active=False` rather than deleting.  The latest record per id wins,
    so rollback is clean (re-append the previous version).

    The registry stores templates and never touches execution.
    """

    def __init__(self, path: str) -> None:
        self._store = JsonlStore(path)

    # ------------------------------------------------------------------ #
    # Write                                                                #
    # ------------------------------------------------------------------ #

    def register(self, template: SkillTemplate) -> SkillTemplate:
        """Append a new skill template.  Assigns id if not set."""
        if not template.id:
            template = SkillTemplate(
                id=make_id("skill", self._store.count() + 1, template.name),
                **{k: v for k, v in template.__dict__.items() if k != "id"},
            )
        self._store.append(template.to_dict())
        return template

    def retire(self, skill_id: str) -> bool:
        """Mark a skill inactive (append-only tombstone). Returns False if not found."""
        skill = self.get(skill_id)
        if skill is None:
            return False
        retired = SkillTemplate.from_dict({**skill.to_dict(), "active": False,
                                           "version": skill.version + 1})
        self._store.append(retired.to_dict())
        return True

    # ------------------------------------------------------------------ #
    # Read                                                                 #
    # ------------------------------------------------------------------ #

    def _current(self) -> dict[str, SkillTemplate]:
        """Latest record per id (last-write-wins)."""
        latest: dict[str, SkillTemplate] = {}
        for row in self._store.all():
            t = SkillTemplate.from_dict(row)
            latest[t.id] = t
        return latest

    def get(self, skill_id: str) -> SkillTemplate | None:
        return self._current().get(skill_id)

    def active_skills(self) -> list[SkillTemplate]:
        return [t for t in self._current().values() if t.active]

    # ------------------------------------------------------------------ #
    # Matching                                                             #
    # ------------------------------------------------------------------ #

    def match(self, task: str) -> tuple[SkillTemplate, dict[str, str]] | None:
        """Return the first active skill that matches the task and can bind params.

        Conservative: returns None if no skill matches confidently.
        The planner calls this in front of normal planning; None → fall back.
        """
        for skill in self.active_skills():
            if skill.matches(task):
                params = skill.extract_params(task)
                if params is not None:
                    return skill, params
        return None
