"""Auto-skill synthesis: mine the plan journal for repeated successful plan
shapes, generalize them into skill templates, and propose them through the
existing promotion gate.

Delegates to SkillPromoter (skills/promoter.py) for the deterministic mining
and generalization.  The SynthesizedSkill and SynthesisResult types are
preserved for the autonomous loop.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..memory.store import MemoryStore
from ..planner.plan import MultiStepPlan, PlanStore
from ..skills.promoter import SkillCandidate, SkillPromoter, candidate_to_template
from ..skills.registry import SkillStep

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Types (preserved for autonomous-loop compatibility)
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
    """Extract completed plan shapes from the plan sidecar directory."""

    def __init__(self, memory: MemoryStore | None = None, plan_store_dir: str = ".aetheris_data/plans") -> None:
        self._memory = memory
        self._plan_dir = plan_store_dir

    def completed_plans(self) -> list[MultiStepPlan]:
        """Return all plans that completed successfully, loaded from sidecars."""
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

    def plan_shapes(self, plans: list[MultiStepPlan]) -> dict:
        """Group plans by tool-sequence shape (ignoring concrete args)."""
        groups: dict = {}
        for plan in plans:
            key = tuple((s.tool, tuple(s.depends_on)) for s in plan.steps)
            groups.setdefault(key, []).append(plan)
        return groups


# ---------------------------------------------------------------------------
# Skill synthesizer (delegates to SkillPromoter)
# ---------------------------------------------------------------------------

class AutoSkillSynthesizer:
    """Detect repeated successful plan patterns and synthesize skill templates.

    Delegates mining + generalization to SkillPromoter.  The promotion gate
    (SkillComparison) is run per candidate.
    """

    def __init__(
        self,
        memory: MemoryStore,
        workspace_root: str,
        registry,  # SkillRegistry — avoid circular import
        min_occurrences: int = 3,
    ) -> None:
        self._memory = memory
        self._root = workspace_root
        self._registry = registry
        self._min_occurrences = min_occurrences
        self._miner = PlanJournalMiner()

    def synthesize(self) -> SynthesisResult:
        """Run one synthesis cycle: mine -> cluster -> propose -> gate."""
        proposed: list[SynthesizedSkill] = []
        promoted: list[str] = []
        rejected: list[str] = []
        errors: list[str] = []

        try:
            plans = self._miner.completed_plans()
            promoter = SkillPromoter(min_recurrence=self._min_occurrences)
            candidates = promoter.candidates(plans, memory=self._memory)
        except Exception as exc:
            errors.append(f"plan mining failed: {exc}")
            return SynthesisResult(proposed=[], promoted=[], rejected=[], errors=errors)

        for cand in candidates:
            try:
                syn = self._to_synthesized(cand)
                proposed.append(syn)
                accepted = self._gate_skill(cand)
                if accepted:
                    promoted.append(cand.name)
                else:
                    rejected.append(cand.name)
            except Exception as exc:
                errors.append(f"synthesis failed for {cand.name}: {exc}")

        return SynthesisResult(
            proposed=proposed, promoted=promoted, rejected=rejected, errors=errors
        )

    def _to_synthesized(self, cand: SkillCandidate) -> SynthesizedSkill:
        return SynthesizedSkill(
            name=cand.name,
            description=(
                f"Auto-synthesized skill for "
                f"{', '.join(s.tool for s in cand.steps)} sequence. "
                f"Discovered from {cand.provenance.get('recurrence', 0)} executions."
            ),
            trigger_hint=cand.trigger,
            params=list(cand.params),
            steps=list(cand.steps),
            occurrences=cand.provenance.get("recurrence", 0),
            confidence=min(1.0, cand.provenance.get("recurrence", 0) / 10.0),
            source_plan_ids=cand.provenance.get("source_task_ids", []),
        )

    def _gate_skill(self, cand: SkillCandidate) -> bool:
        """Run the candidate through the SkillComparison gate."""
        try:
            from ..evaluation.compare import SkillComparison
            template = candidate_to_template(cand)
            from ..evaluation.cases import skill_workflow_suite
            suite = skill_workflow_suite(self._root)
            comp = SkillComparison(self._memory, self._root)
            result = comp.run(suite, skill=template)
            return result.accepted
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Backward-compat wrappers used by tests (delegate to SkillPromoter) #
    # ------------------------------------------------------------------ #

    def _extract_params(self, steps: list) -> dict | None:
        """Extract param names -> example values from plan step args."""
        args = [s.arg for s in steps]
        promoter = SkillPromoter()
        params, _ = promoter._diff_args(args)
        if params is None:
            return None
        result: dict[str, str] = {}
        parsed_list = []
        for a in args:
            try:
                parsed_list.append(json.loads(a))
            except (json.JSONDecodeError, TypeError):
                return None
        all_keys: set[str] = set()
        for obj in parsed_list:
            all_keys.update(obj.keys())
        for key in sorted(all_keys):
            str_vals = [obj[key] for obj in parsed_list if isinstance(obj.get(key), str)]
            if str_vals:
                param_name = re.sub(r"[^a-z0-9_]", "_", key.lower())
                result[param_name] = str_vals[0]
        return result if result else None

    def _generalize_arg(self, arg: str, params: dict[str, str]) -> str:
        """Replace concrete param values with {param} slots."""
        try:
            obj = json.loads(arg)
            result = obj
            if isinstance(result, dict):
                for key, val in result.items():
                    param_name = re.sub(r"[^a-z0-9_]", "_", key.lower())
                    if param_name in params and isinstance(val, str) and val == params[param_name]:
                        result[key] = f"{{{param_name}}}"
            return json.dumps(result)
        except (json.JSONDecodeError, TypeError):
            generalized = arg
            for param_name, example in params.items():
                generalized = generalized.replace(example, f"{{{param_name}}}")
            return generalized

    def _make_name(self, tools: list[str], params: dict[str, str]) -> str:
        """Generate a readable skill name (backward-compat wrapper)."""
        tool_set = set(tools)
        if tool_set == {"list_dir", "read_file"}:
            return "auto_list_and_read"
        if tool_set == {"write_file", "read_file"}:
            return "auto_write_and_verify"
        if tool_set == {"read_file", "write_file"}:
            return "auto_read_and_write"
        return f"auto_{'_and_'.join(sorted(tool_set))}"

    def _synthesize_from_shape(self, shape_key, plans: list) -> "SynthesizedSkill | None":
        """Build a SynthesizedSkill from a cluster of same-shape plans (backward-compat)."""
        tools = [tool for tool, _ in shape_key]
        if len(set(tools)) < 2:
            return None
        first = plans[0]
        params = self._extract_params(first.steps)
        if not params:
            return None
        steps: list[SkillStep] = []
        for plan_step, (tool, deps) in zip(first.steps, shape_key):
            arg_template = self._generalize_arg(plan_step.arg, params)
            steps.append(SkillStep(
                tool=tool, arg_template=arg_template,
                reason=f"auto: {tool}", depends_on=list(deps),
            ))
        name = self._make_name(tools, params)
        return SynthesizedSkill(
            name=name,
            description=f"Auto-synthesized skill for {', '.join(tools)} sequence.",
            trigger_hint="auto-synthesized skill",
            params=sorted(params.keys()),
            steps=steps,
            occurrences=len(plans),
            confidence=min(1.0, len(plans) / 10.0),
            source_plan_ids=[p.task_id for p in plans],
        )
