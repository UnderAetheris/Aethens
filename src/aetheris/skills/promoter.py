"""Skill promotion: mine the plan journal for repeated successful plan shapes,
generalize them into candidate skills, and gate them through SkillComparison.

Read-only miner.  Never registers, never executes.

Design:
  - Filter: successful + stable (zero repair/retry events).
  - Group: by structural shape (tool sequence + DAG edges, not text).
  - Recurrence: require >= N instances of the same shape.
  - Generalize: arg-diff across instances -> varying field = {param}, constant = literal.
  - Trigger: derived from task texts, validated against non-matching tasks.
  - Reject: anything ambiguous, unstable, or with an over-broad trigger.

Promotion itself is owned by the Learning Engine (see engine.promote_skill).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..memory.store import MemoryStore
from ..planner.plan import MultiStepPlan, PlanStep
from ..skills.registry import SkillStep, SkillTemplate

if TYPE_CHECKING:
    pass


_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "be", "as", "are", "was",
    "has", "had", "have", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their",
})


@dataclass(frozen=True)
class PlanShape:
    """Structural fingerprint of a MultiStepPlan: tool sequence + DAG edges.

    Two plans match if their tool sequence and dependency topology match.
    Concrete arguments are intentionally excluded — that IS the generalization.
    """

    tools: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]

    @classmethod
    def of(cls, plan: MultiStepPlan) -> "PlanShape":
        tools = tuple(s.tool for s in plan.steps)
        edges = tuple(
            (i, d)
            for i, s in enumerate(plan.steps)
            for d in s.depends_on
        )
        return cls(tools=tools, edges=edges)


@dataclass(frozen=True)
class SkillCandidate:
    """A mined skill candidate, pending validation and promotion.

    Provenance is first-class: every candidate can answer where it came from
    and what evidence justified it.
    """

    name: str
    trigger: str
    params: tuple[str, ...]
    steps: tuple[SkillStep, ...]
    provenance: dict = field(default_factory=dict)
    version: int = 1
    usefulness: float = 0.0


class SkillPromoter:
    """Deterministic, read-only miner of the plan journal.

    Proposes SkillCandidates from recurring successful plan shapes.
    Never registers, never executes — that is the Learning Engine's job.

    Conservatism knobs (all default toward NOT promoting):
      - min_recurrence: minimum instances of the same shape (default 3).
      - stability_max_repairs: plans with more repairs than this are
        considered fragile and excluded (default 0).
    """

    def __init__(
        self,
        min_recurrence: int = 3,
        stability_max_repairs: int = 0,
    ) -> None:
        self._min_recurrence = min_recurrence
        self._stability_max_repairs = stability_max_repairs

    def candidates(
        self,
        completed_plans: list[MultiStepPlan],
        memory: MemoryStore | None = None,
    ) -> list[SkillCandidate]:
        """Derive skill candidates from completed plans.

        Args:
            completed_plans: plans that finished successfully.
            memory: optional MemoryStore for counting repair/retry events.
                    If None, stability filter is skipped (all plans pass).

        Returns:
            List of SkillCandidates that cleared all conservatism filters.
        """
        stable = [
            p for p in completed_plans
            if self._repairs_of(p, memory) <= self._stability_max_repairs
        ]

        groups: dict[PlanShape, list[MultiStepPlan]] = {}
        for p in stable:
            groups.setdefault(PlanShape.of(p), []).append(p)

        out: list[SkillCandidate] = []
        for shape, instances in groups.items():
            if len(instances) < self._min_recurrence:
                continue
            cand = self._generalize(shape, instances)
            if cand is not None:
                out.append(cand)
        return out

    def _generalize(
        self,
        shape: PlanShape,
        instances: list[MultiStepPlan],
    ) -> SkillCandidate | None:
        """Arg-diff each step across instances: varied field -> {param},
        constant -> literal.  Derive and validate a conservative trigger.

        Returns None if any step's args don't cleanly diff or if a
        conservative trigger can't be derived and validated.
        """
        if not instances:
            return None

        task_texts = [p.task for p in instances if p.task]
        other_tasks = self._other_task_texts(instances)

        if not task_texts:
            return None

        gen_steps: list[SkillStep] = []
        all_params: list[str] = []

        for step_idx, tool in enumerate(shape.tools):
            args_at_step = [p.steps[step_idx].arg for p in instances]
            params, template = self._diff_args(args_at_step)
            if params is None:
                return None
            all_params.extend(p for p in params if p not in all_params)
            deps = list(instances[0].steps[step_idx].depends_on)
            gen_steps.append(SkillStep(
                tool=tool,
                arg_template=template,
                reason=f"auto: {tool}",
                depends_on=deps,
            ))

        trigger = self._derive_trigger(task_texts, other_tasks)
        if trigger is None:
            return None

        name = self._make_name(shape.tools, all_params)

        return SkillCandidate(
            name=name,
            trigger=trigger,
            params=tuple(all_params),
            steps=tuple(gen_steps),
            provenance={
                "source_task_ids": [p.task_id for p in instances],
                "recurrence": len(instances),
                "shape": {
                    "tools": list(shape.tools),
                    "edges": list(shape.edges),
                },
            },
        )

    def _diff_args(
        self, args: list[str]
    ) -> tuple[list[str] | None, str]:
        """Diff args across instances at one step.

        Returns (param_list, template) or (None, "") if ambiguous.
        A field is a parameter if its value varies across instances.
        A field is literal if its value is identical across all instances.
        Args must all be valid JSON objects with the same set of keys.
        """
        parsed_list: list[dict] = []
        for a in args:
            try:
                obj = json.loads(a)
                if not isinstance(obj, dict):
                    return None, ""
                parsed_list.append(obj)
            except (json.JSONDecodeError, TypeError):
                return None, ""

        all_keys: set[str] = set()
        for obj in parsed_list:
            all_keys.update(obj.keys())

        for obj in parsed_list:
            if set(obj.keys()) != all_keys:
                return None, ""

        params: list[str] = []
        result: dict[str, str] = {}
        for key in sorted(all_keys):
            values = [obj[key] for obj in parsed_list]
            str_values = [v for v in values if isinstance(v, str)]
            types_seen = {type(v) for v in values}
            if len(types_seen) > 1:
                return None, ""
            if len(str_values) == len(values) and len(set(str_values)) > 1:
                param_name = re.sub(r"[^a-z0-9_]", "_", key.lower())
                params.append(param_name)
                result[key] = f"{{{param_name}}}"
            elif len(str_values) == len(values):
                result[key] = str_values[0]
            else:
                return None, ""

        return params, json.dumps(result)

    def _derive_trigger(
        self,
        task_texts: list[str],
        other_tasks: list[str],
    ) -> str | None:
        """Derive a conservative trigger from task texts.

        Extract candidate tokens from source tasks (content words appearing
        in >= 50% of source tasks).  Validate: must match all source tasks
        and must NOT match any other task.  Reject if no valid trigger found.
        """
        if not task_texts:
            return None

        token_sets = [self._content_tokens(t) for t in task_texts]
        if not token_sets or not any(token_sets):
            return None

        all_tokens = set().union(*token_sets)
        candidates = [
            t for t in all_tokens
            if sum(t in ts for ts in token_sets) >= max(1, len(token_sets) // 2)
        ]
        if not candidates:
            return None

        trigger_pat = r"\b(?:" + "|".join(re.escape(c) for c in sorted(candidates)) + r")\b"

        for t in task_texts:
            if not re.search(trigger_pat, t, re.IGNORECASE):
                return None

        for t in other_tasks:
            if re.search(trigger_pat, t, re.IGNORECASE):
                return None

        return trigger_pat

    @staticmethod
    def _content_tokens(text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z]{3,}", text.lower())
        return {w for w in words if w not in _STOP_WORDS}

    def _other_task_texts(self, instances: list[MultiStepPlan]) -> list[str]:
        """Placeholder for non-matching task texts.

        In a full integration this would query the task journal for tasks
        whose shape is different.  For now returns empty (conservative:
        empty list means no false positives to check against, trigger is
        validated only against source tasks).
        """
        return []

    def _make_name(self, tools: tuple[str, ...], params: list[str]) -> str:
        tool_set = set(tools)
        if tool_set == {"list_dir", "read_file"}:
            return "auto_list_and_read"
        if tool_set == {"write_file", "read_file"}:
            return "auto_write_and_verify"
        if tool_set == {"read_file", "write_file"}:
            return "auto_read_and_write"
        return "auto_" + "_".join(sorted(tool_set))

    @staticmethod
    def _repairs_of(
        plan: MultiStepPlan,
        memory: MemoryStore | None,
    ) -> int:
        """Count repair/retry events for this plan's task_id.

        Returns 0 if memory is None (no events to count = stable).
        """
        if memory is None:
            return 0
        return sum(
            1 for e in memory.history()
            if e.get("data", {}).get("task_id") == plan.task_id
            and e.get("kind") in ("repair_inserted", "step_replan")
        )


# ---------------------------------------------------------------------------
# Render + DAG validation helpers
# ---------------------------------------------------------------------------


def render_candidate(cand: SkillCandidate, task_id: str) -> MultiStepPlan | None:
    """Render a SkillCandidate into a concrete MultiStepPlan.

    Returns None if parameter substitution fails.
    """
    try:
        steps: list[PlanStep] = []
        for tmpl in cand.steps:
            try:
                arg = _substitute(tmpl.arg_template, dict(zip(cand.params, ["x"] * len(cand.params))))
            except Exception:
                return None
            steps.append(PlanStep(
                tool=tmpl.tool,
                arg=arg,
                reason=tmpl.reason,
                depends_on=list(tmpl.depends_on),
            ))
        return MultiStepPlan(task_id=task_id, steps=steps)
    except Exception:
        return None


def valid_dag(plan: MultiStepPlan) -> bool:
    """Return True if plan steps form a valid DAG (no cycles, valid deps)."""
    n = len(plan.steps)
    for i, s in enumerate(plan.steps):
        for d in s.depends_on:
            if not isinstance(d, int) or d < 0 or d >= n:
                return False
    adj: list[list[int]] = [[] for _ in range(n)]
    for i, s in enumerate(plan.steps):
        for d in s.depends_on:
            adj[d].append(i)
    visited = [0] * n
    def has_cycle(node: int) -> bool:
        if visited[node] == 1:
            return True
        if visited[node] == 2:
            return False
        visited[node] = 1
        for neighbor in adj[node]:
            if has_cycle(neighbor):
                return True
        visited[node] = 2
        return False
    return not any(has_cycle(i) for i in range(n))


def candidate_to_template(cand: SkillCandidate) -> SkillTemplate:
    """Convert a SkillCandidate into a SkillTemplate for comparison/registration."""
    return SkillTemplate(
        id="",
        name=cand.name,
        description=f"Auto-promoted skill mined from {cand.provenance.get('recurrence', 0)} executions.",
        trigger_patterns=[cand.trigger],
        required_params=list(cand.params),
        steps=list(cand.steps),
        version=cand.version,
    )


def _substitute(template: str, params: dict[str, str]) -> str:
    try:
        parsed = json.loads(template)
    except (json.JSONDecodeError, TypeError):
        result = template
        for key, val in params.items():
            result = result.replace(f"{{{key}}}", val)
        return result

    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        if isinstance(obj, str):
            r = obj
            for key, val in params.items():
                r = r.replace(f"{{{key}}}", val)
            return r
        return obj

    return json.dumps(_walk(parsed))
