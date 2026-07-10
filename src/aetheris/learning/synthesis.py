"""Auto-skill synthesis: mine the plan journal for repeated successful plan
shapes, generalize them into skill templates, and propose them through the
existing promotion gate.

Design:
- Scan MemoryStore for successful MultiStepPlan executions (plan_created +
  step_done events that form a complete plan).
- Cluster plans by tool sequence (ignoring concrete args).
- For each cluster with count >= threshold, extract the common arg pattern,
  derive a trigger phrase from the task text, and build a SkillTemplate.
- The proposed skill is measured through the existing SkillComparison gate
  before registration.

No changes to the safe spine: a synthesized skill is still only a rendered
MultiStepPlan, still gated by SafetyLayer, still inherits Reflection.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..memory.store import MemoryStore
from ..planner.plan import MultiStepPlan, PlanStep
from ..skills.registry import SkillRegistry, SkillStep, SkillTemplate


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SynthesizedSkill:
    """A skill candidate mined from the plan journal."""
    name: str
    description: str
    trigger_hint: str
    params: list[str]
    steps: list[SkillStep]
    occurrences: int
    confidence: float
    source_plan_ids: list[str] = field(default_factory=list)


@dataclass
class SynthesisResult:
    """Outcome of one synthesis cycle."""
    proposed: list[SynthesizedSkill]
    promoted: list[str]
    rejected: list[str]
    errors: list[str]


# ---------------------------------------------------------------------------
# Plan journal miner
# ---------------------------------------------------------------------------

class PlanJournalMiner:
    """Extract completed plan shapes from the memory event log."""

    def __init__(self, memory: MemoryStore, plan_store_dir: str = ".aetheris_data/plans"):
        self._memory = memory
        self._plan_dir = plan_store_dir

    def completed_plans(self) -> list[MultiStepPlan]:
        """Return all plans that completed successfully, loaded from sidecars."""
        from ..planner.plan import PlanStore
        store = PlanStore(self._plan_dir)
        plans: list[MultiStepPlan] = []
        for path in store._dir.glob("*.plan.json"):
            try:
                task_id = path.name.removesuffix(".plan.json")
                plan = store.load(task_id)
                if plan and plan.is_complete():
                    plans.append(plan)
            except Exception:
                pass
        return plans

    def plan_shapes(self, plans: list[MultiStepPlan]) -> dict[str, list[MultiStepPlan]]:
        """Group plans by their tool-sequence shape (ignoring concrete args).

        Returns a dict mapping shape-key -> list of plans with that shape.
        Shape key is a tuple of (tool, depends_on) pairs.
        """
        groups: dict[str, list[MultiStepPlan]] = {}
        for plan in plans:
            key = tuple(
                (s.tool, tuple(s.depends_on)) for s in plan.steps
            )
            groups.setdefault(key, []).append(plan)
        return groups


# ---------------------------------------------------------------------------
# Skill synthesizer
# ---------------------------------------------------------------------------

class AutoSkillSynthesizer:
    """Detect repeated successful plan patterns and synthesize skill templates.

    The synthesizer is conservative:
    - Minimum occurrence threshold before proposing.
    - Trigger phrases are derived from the task text (first verb phrase).
    - Params are generalized from concrete values.
    - Proposed skills must clear the existing SkillComparison gate before
      they are registered.
    """

    def __init__(
        self,
        memory: MemoryStore,
        workspace_root: str,
        registry: SkillRegistry,
        min_occurrences: int = 3,
    ) -> None:
        self._memory = memory
        self._root = workspace_root
        self._registry = registry
        self._min_occurrences = min_occurrences
        self._miner = PlanJournalMiner(memory)

    def synthesize(self) -> SynthesisResult:
        """Run one synthesis cycle: mine -> cluster -> propose -> gate."""
        proposed: list[SynthesizedSkill] = []
        promoted: list[str] = []
        rejected: list[str] = []
        errors: list[str] = []

        try:
            plans = self._miner.completed_plans()
            shapes = self._miner.plan_shapes(plans)
        except Exception as exc:
            errors.append(f"plan mining failed: {exc}")
            return SynthesisResult(proposed=[], promoted=[], rejected=[], errors=errors)

        for shape_key, shape_plans in shapes.items():
            if len(shape_plans) < self._min_occurrences:
                continue

            try:
                skill = self._synthesize_from_shape(shape_key, shape_plans)
                if skill is None:
                    continue
                proposed.append(skill)
                accepted = self._gate_skill(skill)
                if accepted:
                    promoted.append(skill.name)
                else:
                    rejected.append(skill.name)
            except Exception as exc:
                errors.append(f"synthesis failed for {shape_key}: {exc}")

        return SynthesisResult(
            proposed=proposed, promoted=promoted, rejected=rejected, errors=errors
        )

    def _synthesize_from_shape(
        self, shape_key: tuple[tuple[str, tuple[int, ...]], ...], plans: list[MultiStepPlan]
    ) -> SynthesizedSkill | None:
        """Build a SynthesizedSkill from a cluster of same-shape plans."""
        tools = [tool for tool, _ in shape_key]
        if len(set(tools)) < 2:
            return None  # single-tool plans are not worth templating

        # Derive params from first plan's concrete args.
        first = plans[0]
        params = self._extract_params(first.steps)
        if not params:
            return None

        # Build steps with {param} slots.
        steps: list[SkillStep] = []
        for plan_step, (tool, deps) in zip(first.steps, shape_key):
            arg_template = self._generalize_arg(plan_step.arg, params)
            steps.append(SkillStep(
                tool=tool,
                arg_template=arg_template,
                reason=f"auto: {tool}",
                depends_on=list(deps),
            ))

        # Derive a trigger hint from task texts.
        trigger_hint = self._derive_trigger([p.task_id for p in plans])

        name = self._make_name(tools, params)
        description = (
            f"Auto-synthesized skill for {', '.join(tools)} sequence. "
            f"Discovered from {len(plans)} successful executions."
        )

        return SynthesizedSkill(
            name=name,
            description=description,
            trigger_hint=trigger_hint,
            params=sorted(params.keys()),
            steps=steps,
            occurrences=len(plans),
            confidence=min(1.0, len(plans) / 10.0),
            source_plan_ids=[p.task_id for p in plans],
        )

    def _extract_params(self, steps: list[PlanStep]) -> dict[str, str] | None:
        """Extract {param} slots from plan step args.

        Looks for repeated structural patterns in JSON args and produces
        a mapping of param_name -> example_value.
        """
        params: dict[str, str] = {}
        for step in steps:
            try:
                arg_obj = json.loads(step.arg)
                if isinstance(arg_obj, dict):
                    for key, val in arg_obj.items():
                        if isinstance(val, str) and val:
                            param_name = self._sanitize_param(key)
                            params[param_name] = val
            except (json.JSONDecodeError, TypeError):
                continue
        return params if params else None

    @staticmethod
    def _sanitize_param(name: str) -> str:
        return re.sub(r"[^a-z0-9_]", "_", name.lower())

    def _generalize_arg(self, arg: str, params: dict[str, str]) -> str:
        """Replace concrete param values in a JSON arg with {param} slots."""
        try:
            obj = json.loads(arg)
            result = obj
            if isinstance(result, dict):
                for key, val in result.items():
                    param_name = self._sanitize_param(key)
                    if param_name in params and isinstance(val, str):
                        result[key] = f"{{{param_name}}}"
            return json.dumps(result)
        except (json.JSONDecodeError, TypeError):
            # Fallback: simple string replacement.
            generalized = arg
            for param_name, example in params.items():
                generalized = generalized.replace(example, f"{{{param_name}}}")
            return generalized

    def _derive_trigger(self, task_ids: list[str]) -> str:
        """Derive a conservative trigger phrase from task IDs or context.

        In a real system this would look at the original task texts stored
        in the memory journal.  For now we produce a generic trigger based
        on the tool sequence.
        """
        # Placeholder: real implementation would mine task texts from memory.
        return "auto-synthesized skill"

    def _make_name(self, tools: list[str], params: dict[str, str]) -> str:
        """Generate a readable skill name from its tool sequence and params."""
        if set(tools) == {"list_dir", "read_file"}:
            return "auto_list_and_read"
        if set(tools) == {"write_file", "read_file"}:
            return "auto_write_and_verify"
        if set(tools) == {"read_file", "write_file"}:
            return "auto_read_and_write"
        return f"auto_{'_and_'.join(tools)}"

    # ------------------------------------------------------------------ #
    # Promotion gate                                                      #
    # ------------------------------------------------------------------ #

    def _gate_skill(self, skill: SynthesizedSkill) -> bool:
        """Run the synthesized skill through the SkillComparison gate.

        Returns True if the skill clears the gate (completion >= baseline,
        no regressions, safety-neutral).
        """
        try:
            from ..evaluation.compare import SkillComparison, skill_workflow_suite
            template = SkillTemplate(
                id="",
                name=skill.name,
                description=skill.description,
                trigger_patterns=[re.escape(skill.trigger_hint)],
                required_params=skill.params,
                steps=skill.steps,
                version=1,
            )
            suite = skill_workflow_suite(self._root)
            comp = SkillComparison(self._memory, self._root)
            result = comp.run(suite, skill=template)
            return result.accepted
        except Exception:
            return False
