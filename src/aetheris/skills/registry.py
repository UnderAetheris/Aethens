from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..memory.experience_rerank import experience_rerank
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

        Fills `{param}` slots in each step's arg_template, then re-serialises
        through JSON so that special characters (backslashes, quotes) are
        correctly escaped.  Falls back to raw string replacement if the
        template is not valid JSON.  The result is an ordinary MultiStepPlan
        — indistinguishable from one the planner decomposed itself.
        """
        steps: list[PlanStep] = []
        for tmpl_step in self.steps:
            arg = self._substitute(tmpl_step.arg_template, params)
            steps.append(PlanStep(
                tool=tmpl_step.tool,
                arg=arg,
                reason=f"[skill:{self.name}] {tmpl_step.reason}",
                depends_on=list(tmpl_step.depends_on),
            ))
        return MultiStepPlan(task_id=task_id, steps=steps,
                              source=f"skill:{self.name}:v{self.version}")

    @staticmethod
    def _substitute(template: str, params: dict[str, str]) -> str:
        """Replace {param} slots in a JSON template and re-serialise."""
        try:
            parsed = json.loads(template)
        except (json.JSONDecodeError, TypeError):
            for key, val in params.items():
                template = template.replace(f"{{{key}}}", val)
            return template

        def _walk(obj):
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(v) for v in obj]
            if isinstance(obj, str):
                result = obj
                for key, val in params.items():
                    result = result.replace(f"{{{key}}}", val)
                return result
            return obj

        return json.dumps(_walk(parsed))

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

    def match(
        self, task: str, experience=None
    ) -> tuple[SkillTemplate, dict[str, str]] | None:
        """Return the best active skill that matches the task and can bind params.

        Conservative: returns None if no skill matches confidently.
        The planner calls this in front of normal planning; None → fall back.

        When an ``ExperienceMemory`` handle is supplied, candidate skills are
        re-ranked by real-run history (``experience_rerank``) *without* adding
        or removing any option.  With consumption off, or no confident lesson,
        the result is the original first-match order (byte-identical floor).
        """
        candidates = [
            (s, s.extract_params(task))
            for s in self.active_skills()
            if s.matches(task) and s.extract_params(task) is not None
        ]
        if not candidates:
            return None
        if experience is None:
            return candidates[0]

        lessons = experience.query()
        if not lessons:
            return candidates[0]

        ranked = experience_rerank(
            candidates,
            lessons,
            keyfn=lambda sc: f"{sc[0].name} {' '.join(sc[0].trigger_patterns)}",
        )
        return ranked[0]
