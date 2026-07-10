"""Skill System v0 — 12 tests.

  1.  register a skill and retrieve it
  2.  skill matches task via trigger pattern
  3.  skill does not match unrelated task
  4.  extract_params returns bound params
  5.  extract_params returns None when required param missing
  6.  render produces a valid MultiStepPlan (ordinary, no skill runtime)
  7.  rendered plan is indistinguishable from planner-decomposed plan
  8.  planner uses skill when registry matches (skill fires in front of normal planning)
  9.  planner falls back to normal planning when no skill matches
 10.  safety gate still applies to every skill step (no privilege)
 11.  reflection repairs a failing skill step (self-healing inherited)
 12.  retire (demotion) marks skill inactive; match no longer fires
 13.  promote_skill registers under two-clause gate; demote_skill retires it
"""
from __future__ import annotations

import json
from pathlib import Path

from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore
from aetheris.planner.planner import Planner
from aetheris.safety.guard import SafetyLayer, build_default_rules
from aetheris.skills.registry import SkillRegistry, SkillStep, SkillTemplate
from aetheris.tools.base import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry(tmp_path) -> SkillRegistry:
    return SkillRegistry(str(tmp_path / "skills.jsonl"))


def _read_write_skill() -> SkillTemplate:
    """A two-step skill: read a file then write a summary."""
    return SkillTemplate(
        id="",
        name="read_then_write",
        description="Read a source file and write its content to a destination.",
        trigger_patterns=[r"copy\s+path=", r"read.*then.*write.*path="],
        required_params=["src", "dst"],
        steps=[
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{src}"}',
                reason="read source",
                depends_on=[],
            ),
            SkillStep(
                tool="write_file",
                arg_template='{"path": "{dst}", "content": "copied"}',
                reason="write destination",
                depends_on=[0],
            ),
        ],
    )


def _echo_skill() -> SkillTemplate:
    return SkillTemplate(
        id="",
        name="greet",
        description="Echo a greeting.",
        trigger_patterns=[r"greet\s+name="],
        required_params=["name"],
        steps=[
            SkillStep(tool="echo", arg_template="hello {name}", reason="greet", depends_on=[]),
        ],
    )


def _exec(tmp_path, safe_mode=False, skills: SkillRegistry | None = None):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
        reflection_enabled=True,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))

    registry = ToolRegistry()
    registry.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    registry.register(Tool(name="read_file", description="read",
                           run=lambda a: Path(json.loads(a)["path"]).read_text(), safe=True))
    registry.register(Tool(name="write_file", description="write",
                           run=lambda a: _write(a), safe=not safe_mode))

    ctrl_mem = MemoryStore(str(tmp_path / "ctrl_mem.jsonl"))
    safety = SafetyLayer(ctrl_mem, safe_mode=safe_mode, rules=build_default_rules(str(tmp_path)))
    planner = Planner(
        registry_tools=tuple(registry.list()),
        skills=skills,
    )
    ctrl = Controller(config, registry=registry, memory=ctrl_mem, safety=safety,
                      planner=planner)
    ex = ExecutiveController(config, queue, mem, controller=ctrl,
                             max_retries=3, plan_store=plan_store)
    return ex, queue, mem, plan_store, ctrl


def _write(arg: str) -> str:
    data = json.loads(arg)
    Path(data["path"]).write_text(data["content"], encoding="utf-8")
    return f"wrote {data['path']}"


def _drain(ex, queue, task_id, max_ticks=15):
    for _ in range(max_ticks):
        state = queue.get(task_id).state
        if state in (TaskState.DONE, TaskState.FAILED,
                     TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED):
            break
        ex.run_once()
    return queue.get(task_id).state


# ---------------------------------------------------------------------------
# 1. Register and retrieve
# ---------------------------------------------------------------------------

def test_register_and_retrieve(tmp_path):
    reg = _registry(tmp_path)
    skill = reg.register(_echo_skill())
    assert skill.id != ""
    retrieved = reg.get(skill.id)
    assert retrieved is not None
    assert retrieved.name == "greet"
    assert retrieved.active is True


# ---------------------------------------------------------------------------
# 2. Skill matches task via trigger pattern
# ---------------------------------------------------------------------------

def test_skill_matches_trigger_pattern(tmp_path):
    reg = _registry(tmp_path)
    reg.register(_echo_skill())
    result = reg.match("greet name=Alice")
    assert result is not None
    skill, params = result
    assert skill.name == "greet"
    assert params["name"] == "Alice"


# ---------------------------------------------------------------------------
# 3. Skill does not match unrelated task
# ---------------------------------------------------------------------------

def test_skill_does_not_match_unrelated_task(tmp_path):
    reg = _registry(tmp_path)
    reg.register(_echo_skill())
    assert reg.match("list path=/tmp") is None
    assert reg.match("hello there") is None


# ---------------------------------------------------------------------------
# 4. extract_params returns bound params
# ---------------------------------------------------------------------------

def test_extract_params_returns_bound_params():
    skill = _echo_skill()
    params = skill.extract_params("greet name=Bob")
    assert params == {"name": "Bob"}


# ---------------------------------------------------------------------------
# 5. extract_params returns None when required param missing
# ---------------------------------------------------------------------------

def test_extract_params_returns_none_when_param_missing():
    skill = _echo_skill()
    assert skill.extract_params("greet someone") is None


# ---------------------------------------------------------------------------
# 6. render produces a valid MultiStepPlan
# ---------------------------------------------------------------------------

def test_render_produces_valid_multistep_plan(tmp_path):
    skill = _echo_skill()
    params = {"name": "Carol"}
    plan = skill.render("task-1", params)

    assert isinstance(plan, MultiStepPlan)
    assert plan.task_id == "task-1"
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "echo"
    assert plan.steps[0].arg == "hello Carol"
    assert "[skill:greet]" in plan.steps[0].reason


# ---------------------------------------------------------------------------
# 7. Rendered plan is indistinguishable from planner-decomposed plan
# ---------------------------------------------------------------------------

def test_rendered_plan_is_ordinary_multistep_plan(tmp_path):
    """A rendered skill plan is a plain MultiStepPlan — no special type, no skill runtime."""
    skill = _echo_skill()
    plan = skill.render("t1", {"name": "Dave"})

    # It's exactly a MultiStepPlan with PlanSteps — same type the planner produces.
    assert type(plan) is MultiStepPlan
    assert all(type(s) is PlanStep for s in plan.steps)
    # No skill-specific attributes on the plan.
    assert not hasattr(plan, "skill_id")
    assert not hasattr(plan, "skill_name")


# ---------------------------------------------------------------------------
# 8. Planner uses skill when registry matches
# ---------------------------------------------------------------------------

def test_planner_uses_skill_when_registry_matches(tmp_path):
    reg = _registry(tmp_path)
    reg.register(_echo_skill())

    planner = Planner(registry_tools=("echo",), skills=reg)
    plan = planner.plan_multi("greet name=Eve", task_id="t1")

    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "echo"
    assert "Eve" in plan.steps[0].arg
    assert "[skill:greet]" in plan.steps[0].reason


# ---------------------------------------------------------------------------
# 9. Planner falls back to normal planning when no skill matches
# ---------------------------------------------------------------------------

def test_planner_falls_back_when_no_skill_matches(tmp_path):
    reg = _registry(tmp_path)
    reg.register(_echo_skill())

    planner = Planner(registry_tools=("echo", "read_file"), skills=reg)
    plan = planner.plan_multi("hello there", task_id="t2")

    # Normal planning: echo for a chat task.
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "echo"
    assert "[skill:" not in plan.steps[0].reason


# ---------------------------------------------------------------------------
# 10. Safety gate still applies to every skill step
# ---------------------------------------------------------------------------

def test_safety_gate_applies_to_skill_steps(tmp_path):
    """write_file is unsafe in safe_mode; a skill that includes it must be blocked."""
    reg = _registry(tmp_path)
    skill = SkillTemplate(
        id="",
        name="unsafe_write",
        description="Write a file (unsafe in safe_mode).",
        trigger_patterns=[r"unsafe_write\s+dst="],
        required_params=["dst"],
        steps=[
            SkillStep(
                tool="write_file",
                arg_template='{{"path": "{dst}", "content": "hi"}}',
                reason="write",
                depends_on=[],
            ),
        ],
    )
    reg.register(skill)

    ex, queue, mem, plan_store, ctrl = _exec(tmp_path, safe_mode=True, skills=reg)
    rec = queue.enqueue(f"unsafe_write dst={tmp_path}/out.txt")
    state = _drain(ex, queue, rec.id)

    # Safety blocked — task must not be DONE.
    assert state != TaskState.DONE
    assert state in (TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED, TaskState.FAILED)


# ---------------------------------------------------------------------------
# 11. Reflection repairs a failing skill step (self-healing inherited)
# ---------------------------------------------------------------------------

def test_reflection_repairs_failing_skill_step(tmp_path):
    """A skill step that fails transiently is repaired by Reflection — no skill-specific code."""
    reg = _registry(tmp_path)
    reg.register(_echo_skill())

    ex, queue, mem, plan_store, ctrl = _exec(tmp_path, safe_mode=False, skills=reg)

    # Patch handle_step to fail once then succeed.
    call_count = {"n": 0}
    original = ctrl.handle_step

    def patched(tool, arg, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient skill step failure")
        return original(tool, arg, **kw)

    ctrl.handle_step = patched

    rec = queue.enqueue("greet name=Frank")
    state = _drain(ex, queue, rec.id)

    assert state == TaskState.DONE
    # Reflection fired (retry).
    kinds = [e["kind"] for e in mem.history()]
    assert "reflection_decision" in kinds


# ---------------------------------------------------------------------------
# 12. Retire marks skill inactive; match no longer fires
# ---------------------------------------------------------------------------

def test_retire_marks_skill_inactive(tmp_path):
    reg = _registry(tmp_path)
    skill = reg.register(_echo_skill())

    assert reg.match("greet name=Grace") is not None

    retired = reg.retire(skill.id)
    assert retired is True

    # After retirement, match returns None.
    assert reg.match("greet name=Grace") is None

    # get() returns the latest (inactive) record.
    latest = reg.get(skill.id)
    assert latest is not None
    assert latest.active is False
    assert latest.version == 2  # bumped on retire


# ---------------------------------------------------------------------------
# 13. promote_skill and demote_skill via LearningEngine
# ---------------------------------------------------------------------------

def test_promote_and_demote_skill(tmp_path):
    from aetheris.evaluation.cases import default_suite
    from aetheris.learning.engine import LearningEngine
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.jsonl"))
    experience = ExperienceStore(str(tmp_path / "experience.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    engine = LearningEngine(mem, str(tmp_path), knowledge, experience, learned)

    reg = _registry(tmp_path)
    skill = _echo_skill()

    # Promote: should succeed (anchors pass at baseline).
    promoted = engine.promote_skill(skill, reg, default_suite(), workspace_root=str(tmp_path))
    assert promoted is True

    active = reg.active_skills()
    assert len(active) == 1
    skill_id = active[0].id

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promoted" in kinds

    # Demote: retire the skill.
    demoted = engine.demote_skill(skill_id, reg, reason="test demotion")
    assert demoted is True
    assert reg.match("greet name=Henry") is None

    kinds2 = [e["kind"] for e in mem.history()]
    assert "skill_demoted" in kinds2
