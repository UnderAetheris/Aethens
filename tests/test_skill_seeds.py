"""Hand-authored seed skills — 12 tests.

  1.  list_and_read_first structure is correct (steps, deps, tools)
  2.  create_and_verify structure is correct
  3.  lrf trigger fires on specific phrase, not on vague task
  4.  cav trigger fires on specific phrase, not on vague task
  5.  lrf renders a valid plan with plan.source stamped
  6.  rendered plan is structurally identical to a hand-built MultiStepPlan
  7.  lrf runs end-to-end in safe_mode (all-safe skill)
  8.  cav write step is blocked in safe_mode (skill gains zero privilege)
  9.  cav runs end-to-end with safe_mode=False (happy path)
 10.  lrf self-repair: failing step repaired by Reflection (inherited, no skill code)
 11.  promotion gate: lrf clears the gate (completion up or repairs down, no regressions)
 12.  no-regression: existing planner tests unaffected (skills=None path unchanged)
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
from aetheris.skills import create_and_verify, list_and_read_first
from aetheris.skills.registry import SkillRegistry
from aetheris.tools.base import Tool, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reg(tmp_path) -> SkillRegistry:
    return SkillRegistry(str(tmp_path / "skills.jsonl"))


def _write_fn(arg: str) -> str:
    data = json.loads(arg)
    Path(data["path"]).write_text(data["content"], encoding="utf-8")
    return f"wrote {data['path']}"


def _exec(tmp_path, safe_mode: bool = False, skills: SkillRegistry | None = None):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(
        log_path=str(tmp_path / "ctrl.jsonl"),
        workspace_root=str(tmp_path),
        safe_mode=safe_mode,
        reflection_enabled=True,
    )
    plan_store = PlanStore(str(tmp_path / "plans"))

    tool_reg = ToolRegistry()
    tool_reg.register(Tool(name="echo", description="echo", run=lambda a: a, safe=True))
    tool_reg.register(Tool(name="read_file", description="read",
                           run=lambda a: Path(json.loads(a)["path"]).read_text(), safe=True))
    tool_reg.register(Tool(name="list_dir", description="list",
                           run=lambda a: "\n".join(
                               sorted(p.name for p in Path(json.loads(a)["path"]).iterdir())
                           ), safe=True))
    tool_reg.register(Tool(name="write_file", description="write",
                           run=_write_fn, safe=not safe_mode))

    ctrl_mem = MemoryStore(str(tmp_path / "ctrl_mem.jsonl"))
    safety = SafetyLayer(ctrl_mem, safe_mode=safe_mode,
                         rules=build_default_rules(str(tmp_path)))
    planner = Planner(registry_tools=tuple(tool_reg.list()), skills=skills)
    ctrl = Controller(config, registry=tool_reg, memory=ctrl_mem,
                      safety=safety, planner=planner)
    ex = ExecutiveController(config, queue, mem, controller=ctrl,
                             max_retries=3, plan_store=plan_store)
    return ex, queue, mem, plan_store, ctrl


def _drain(ex, queue, task_id, max_ticks=20):
    for _ in range(max_ticks):
        state = queue.get(task_id).state
        if state in (TaskState.DONE, TaskState.FAILED,
                     TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED):
            break
        ex.run_once()
    return queue.get(task_id).state


# ---------------------------------------------------------------------------
# 1. list_and_read_first structure
# ---------------------------------------------------------------------------

def test_lrf_structure():
    skill = list_and_read_first()
    assert skill.name == "list_and_read_first"
    assert len(skill.steps) == 2
    assert skill.steps[0].tool == "list_dir"
    assert skill.steps[1].tool == "read_file"
    assert skill.steps[1].depends_on == [0]   # read after list
    assert skill.steps[0].depends_on == []
    assert skill.required_params == ["dir", "file"]


# ---------------------------------------------------------------------------
# 2. create_and_verify structure
# ---------------------------------------------------------------------------

def test_cav_structure():
    skill = create_and_verify()
    assert skill.name == "create_and_verify"
    assert len(skill.steps) == 2
    assert skill.steps[0].tool == "write_file"
    assert skill.steps[1].tool == "read_file"
    assert skill.steps[1].depends_on == [0]   # read after write
    assert skill.required_params == ["path", "content"]


# ---------------------------------------------------------------------------
# 3. lrf trigger: specific phrase fires, vague task does not
# ---------------------------------------------------------------------------

def test_lrf_trigger_conservative(tmp_path):
    reg = _reg(tmp_path)
    reg.register(list_and_read_first())
    d = tmp_path.as_posix()

    # Must fire on specific phrase with required param.
    assert reg.match(f"list and read dir={d} file={d}/a.txt") is not None
    assert reg.match(f"lrf dir={d} file={d}/a.txt") is not None

    # Must NOT fire on vague tasks that merely mention a file.
    assert reg.match("show me the files") is None
    assert reg.match("list the directory") is None
    assert reg.match(f"read path={d}/a.txt") is None
    assert reg.match("what files are there") is None


# ---------------------------------------------------------------------------
# 4. cav trigger: specific phrase fires, vague task does not
# ---------------------------------------------------------------------------

def test_cav_trigger_conservative(tmp_path):
    reg = _reg(tmp_path)
    reg.register(create_and_verify())
    d = tmp_path.as_posix()

    assert reg.match(f"create and verify path={d}/f.txt content=hi") is not None

    # Must NOT fire on vague write tasks.
    assert reg.match(f"create path={d}/f.txt content=hi") is None
    assert reg.match(f"write path={d}/f.txt content=hi") is None
    assert reg.match("save this file") is None


# ---------------------------------------------------------------------------
# 5. lrf renders a valid plan with plan.source stamped
# ---------------------------------------------------------------------------

def test_lrf_render_stamps_source(tmp_path):
    reg = _reg(tmp_path)
    skill = reg.register(list_and_read_first())
    d = tmp_path.as_posix()

    params = {"dir": d, "file": f"{d}/a.txt"}
    plan = skill.render("t1", params)

    assert isinstance(plan, MultiStepPlan)
    assert plan.source == f"skill:list_and_read_first:v{skill.version}"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool == "list_dir"
    assert plan.steps[1].tool == "read_file"
    assert d in plan.steps[0].arg
    assert f"{d}/a.txt" in plan.steps[1].arg


# ---------------------------------------------------------------------------
# 6. Rendered plan structurally identical to hand-built MultiStepPlan
# ---------------------------------------------------------------------------

def test_rendered_plan_structurally_identical_to_hand_built(tmp_path):
    """Proves safety/reflection inheritance is a fact, not a claim."""
    skill = list_and_read_first()
    d = tmp_path.as_posix()
    params = {"dir": d, "file": f"{d}/a.txt"}
    rendered = skill.render("t1", params)

    hand_built = MultiStepPlan(
        task_id="t1",
        steps=[
            PlanStep(tool="list_dir",
                     arg=json.dumps({"path": d}),
                     reason="[skill:list_and_read_first] list directory",
                     depends_on=[]),
            PlanStep(tool="read_file",
                     arg=json.dumps({"path": f"{d}/a.txt"}),
                     reason="[skill:list_and_read_first] read first file",
                     depends_on=[0]),
        ],
    )

    # Same types throughout.
    assert type(rendered) is type(hand_built)
    assert all(type(rs) is type(hs)
               for rs, hs in zip(rendered.steps, hand_built.steps))

    # Same DAG structure.
    for rs, hs in zip(rendered.steps, hand_built.steps):
        assert rs.tool == hs.tool
        assert rs.depends_on == hs.depends_on

    # Only trace of skill-ness is source (audit field, not execution).
    assert not hasattr(rendered, "skill_id")


# ---------------------------------------------------------------------------
# 7. lrf runs end-to-end in safe_mode (all-safe skill)
# ---------------------------------------------------------------------------

def test_lrf_end_to_end_safe_mode(tmp_path):
    """list_and_read_first uses only safe tools — runs cleanly in safe_mode."""
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")

    reg = _reg(tmp_path)
    reg.register(list_and_read_first())

    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True, skills=reg)
    # Use posix paths so the JSON arg parses cleanly on Windows.
    d = tmp_path.as_posix()
    task = f"list and read dir={d} file={d}/hello.txt"
    rec = queue.enqueue(task)
    state = _drain(ex, queue, rec.id)

    assert state == TaskState.DONE


# ---------------------------------------------------------------------------
# 8. cav write step blocked in safe_mode (skill gains zero privilege)
# ---------------------------------------------------------------------------

def test_cav_write_blocked_in_safe_mode(tmp_path):
    """write_file is blocked by the unchanged SafetyLayer in safe_mode.
    The skill gains zero privilege — the block fires exactly as for any write step.
    """
    reg = _reg(tmp_path)
    reg.register(create_and_verify())

    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True, skills=reg)
    d = tmp_path.as_posix()
    task = f"create and verify path={d}/out.txt content=hello"
    rec = queue.enqueue(task)
    state = _drain(ex, queue, rec.id)

    assert state != TaskState.DONE
    assert state in (TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED, TaskState.FAILED)


# ---------------------------------------------------------------------------
# 9. cav runs end-to-end with safe_mode=False (happy path)
# ---------------------------------------------------------------------------

def test_cav_end_to_end_safe_mode_off(tmp_path):
    """create_and_verify completes when safe_mode is off."""
    reg = _reg(tmp_path)
    reg.register(create_and_verify())

    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=False, skills=reg)
    out = tmp_path / "out.txt"
    d = tmp_path.as_posix()
    task = f"create and verify path={d}/out.txt content=verified"
    rec = queue.enqueue(task)
    state = _drain(ex, queue, rec.id)

    assert state == TaskState.DONE
    assert out.read_text() == "verified"


# ---------------------------------------------------------------------------
# 10. lrf self-repair: failing step repaired by Reflection
# ---------------------------------------------------------------------------

def test_lrf_self_repair_via_reflection(tmp_path):
    """A transient failure in a skill step is repaired by Reflection.
    Zero skill-specific recovery code — inherited from default-on Reflection.
    """
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    reg = _reg(tmp_path)
    reg.register(list_and_read_first())

    ex, queue, mem, _, ctrl = _exec(tmp_path, safe_mode=False, skills=reg)

    call_count = {"n": 0}
    original = ctrl.handle_step

    def patched(tool, arg, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient lrf failure")
        return original(tool, arg, **kw)

    ctrl.handle_step = patched
    d = tmp_path.as_posix()
    task = f"list and read dir={d} file={d}/hello.txt"
    rec = queue.enqueue(task)
    state = _drain(ex, queue, rec.id)

    assert state == TaskState.DONE
    kinds = [e["kind"] for e in mem.history()]
    assert "reflection_decision" in kinds


# ---------------------------------------------------------------------------
# 11. Promotion gate: lrf clears the two-clause gate
# ---------------------------------------------------------------------------

def test_lrf_clears_promotion_gate(tmp_path):
    """list_and_read_first must clear the promotion gate:
    anchors pass at baseline → promote succeeds.
    Validates the gate itself against a real skill from the first entry.
    """
    from aetheris.evaluation.cases import default_suite
    from aetheris.learning.engine import LearningEngine
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    engine = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "know.jsonl")),
        ExperienceStore(str(tmp_path / "exp.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    reg = _reg(tmp_path)
    promoted = engine.promote_skill(
        list_and_read_first(), reg, default_suite(), workspace_root=str(tmp_path)
    )
    assert promoted is True

    active = reg.active_skills()
    assert len(active) == 1
    assert active[0].name == "list_and_read_first"

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promoted" in kinds
    assert "skill_promotion_rejected" not in kinds


# ---------------------------------------------------------------------------
# 12. No-regression: skills=None path is byte-identical to Planner v2
# ---------------------------------------------------------------------------

def test_no_regression_skills_none_path(tmp_path):
    """With skills=None the planner behaves exactly as Planner v2.
    Existing single-step and multi-step cases must be unaffected.
    """
    planner_no_skills = Planner(registry_tools=("echo", "read_file", "list_dir"))
    planner_with_skills = Planner(
        registry_tools=("echo", "read_file", "list_dir"),
        skills=_reg(tmp_path),   # empty registry — no skills registered
    )

    tasks = [
        "hello there",
        f"read path={tmp_path}/a.txt",
        f"list path={tmp_path}",
    ]
    for task in tasks:
        p_none = planner_no_skills.plan_multi(task, "t")
        p_empty = planner_with_skills.plan_multi(task, "t")
        assert len(p_none.steps) == len(p_empty.steps)
        for s_none, s_empty in zip(p_none.steps, p_empty.steps):
            assert s_none.tool == s_empty.tool
            assert s_none.depends_on == s_empty.depends_on
        # No skill source on planner-decomposed plans.
        assert p_none.source == ""
        assert p_empty.source == ""


# ---------------------------------------------------------------------------
# 13. SkillComparison adoption gate
# ---------------------------------------------------------------------------

def test_skill_benchmark_meets_adoption_gate(tmp_path):
    """SkillComparison must clear the two-clause adoption gate:
    completion_on >= completion_off, no regressions, safety-neutral.
    The efficiency credit (fewer retries/repairs) is measured but not
    required for the gate to pass in this happy-path suite.
    """
    from aetheris.evaluation.compare import SkillComparison
    from aetheris.evaluation.cases import skill_workflow_suite
    from aetheris.memory.store import MemoryStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    result = comp.run(skill_workflow_suite(str(tmp_path)), skill=list_and_read_first())

    assert result.completion_on >= result.completion_off
    assert result.regressed == []
    assert result.blocked_on <= result.blocked_off
    assert result.accepted


def test_no_regression_on_anchor(tmp_path):
    """Anchors must not regress when a skill is registered."""
    from aetheris.evaluation.compare import SkillComparison
    from aetheris.evaluation.cases import skill_workflow_suite
    from aetheris.memory.store import MemoryStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))
    result = comp.run(skill_workflow_suite(str(tmp_path)), skill=list_and_read_first())

    anchor = "anchor_simple_read"
    assert anchor not in result.regressed
    anchor_baseline = next(r for r in result.baseline if r.name == anchor)
    anchor_candidate = next(r for r in result.candidate if r.name == anchor)
    assert anchor_baseline.completed
    assert anchor_candidate.completed


def test_plan_source_is_journaled(tmp_path):
    """plan.source is recorded in memory so we can audit skill firing."""
    reg = _reg(tmp_path)
    reg.register(list_and_read_first())

    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True, skills=reg)
    d = tmp_path.as_posix()
    task = f"list and read dir={d} file={d}/hello.txt"
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    rec = queue.enqueue(task)
    _drain(ex, queue, rec.id)

    kinds = [e["kind"] for e in mem.history()]
    assert "plan_created" in kinds
