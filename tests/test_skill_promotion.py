"""Automatic Skill Promotion v0 — 12 tests.

   1.  detects_repeated_plan_shape   — same tool seq >= 3x -> 1 candidate
   2.  ignores_one_off_plans        — no shape recurs 3x -> no candidates
   3.  ignores_unstable_plans       — plans with repairs excluded
   4.  generalization_params_are_varying_fields
   5.  ambiguous_pattern_is_rejected
   6.  candidate_renders_valid_multistep_plan
   7.  successful_promotion_registers_versioned_skill
   8.  rejected_promotion_is_not_registered
   9.  promotion_owned_by_learning_engine_and_reversible
  10.  auto_skill_runs_through_safety_gate
  11.  auto_skill_matches_hand_authored_on_same_workflow
  12.  no_repeated_pattern_leaves_registry_unchanged
"""
from __future__ import annotations

import json
from pathlib import Path

from aetheris.config import Config
from aetheris.controller.controller import Controller
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep, PlanStore, StepStatus
from aetheris.planner.planner import Planner
from aetheris.safety.guard import SafetyLayer, build_default_rules
from aetheris.skills.promoter import (
    SkillPromoter,
    render_candidate,
    valid_dag,
)
from aetheris.skills.registry import SkillRegistry, SkillStep, SkillTemplate
from aetheris.tools.base import Tool, ToolRegistry


# ===========================================================================
# Helpers
# ===========================================================================

def _make_read_plan(task_id: str, path: str, task_text: str = "") -> MultiStepPlan:
    return MultiStepPlan(
        task_id=task_id,
        task=task_text,
        steps=[PlanStep(
            tool="read_file",
            arg=json.dumps({"path": path}),
            reason="read file",
            depends_on=[],
            status=StepStatus.DONE,
        )],
    )


def _make_write_read_plan(task_id: str, path: str, content: str = "x", task_text: str = "") -> MultiStepPlan:
    return MultiStepPlan(
        task_id=task_id,
        task=task_text,
        steps=[
            PlanStep(
                tool="write_file",
                arg=json.dumps({"path": path, "content": content}),
                reason="write file",
                depends_on=[],
                status=StepStatus.DONE,
            ),
            PlanStep(
                tool="read_file",
                arg=json.dumps({"path": path}),
                reason="verify by reading back",
                depends_on=[0],
                status=StepStatus.DONE,
            ),
        ],
    )


def _make_list_read_plan(task_id: str, dir_path: str, file_path: str, task_text: str = "") -> MultiStepPlan:
    return MultiStepPlan(
        task_id=task_id,
        task=task_text,
        steps=[
            PlanStep(
                tool="list_dir",
                arg=json.dumps({"path": dir_path}),
                reason="list directory",
                depends_on=[],
                status=StepStatus.DONE,
            ),
            PlanStep(
                tool="read_file",
                arg=json.dumps({"path": file_path}),
                reason="read file",
                depends_on=[0],
                status=StepStatus.DONE,
            ),
        ],
    )


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
    planner = Planner(
        registry_tools=tuple(tool_reg.list()),
        skills=skills,
    )
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


def _write_skill() -> SkillTemplate:
    return SkillTemplate(
        id="",
        name="unsafe_write",
        description="Write a file (unsafe in safe_mode).",
        trigger_patterns=[r"\bwrite\b.*\bdst="],
        required_params=["dst"],
        steps=[
            SkillStep(
                tool="write_file",
                arg_template='{"path": "{dst}", "content": "hi"}',
                reason="write",
                depends_on=[],
            ),
        ],
    )


def _plan_store_for(tmp_path) -> PlanStore:
    return PlanStore(str(tmp_path / "plans"))


# ===========================================================================
# 1.  Detects repeated plan shape
# ===========================================================================

def test_detects_repeated_plan_shape(tmp_path):
    d = tmp_path.as_posix()
    plans = [
        _make_list_read_plan("t1", d, f"{d}/a.txt", task_text=f"list and read dir={d} file={d}/a.txt"),
        _make_list_read_plan("t2", d, f"{d}/b.txt", task_text=f"list and read dir={d} file={d}/b.txt"),
        _make_list_read_plan("t3", d, f"{d}/c.txt", task_text=f"list and read dir={d} file={d}/c.txt"),
    ]
    for p in plans:
        _plan_store_for(tmp_path).save(p)

    cands = SkillPromoter(min_recurrence=3).candidates(plans)
    assert len(cands) == 1
    assert cands[0].steps[0].tool == "list_dir"
    assert cands[0].steps[1].tool == "read_file"


# ===========================================================================
# 2.  Ignores one-off plans
# ===========================================================================

def test_ignores_one_off_plans(tmp_path):
    d = tmp_path.as_posix()
    plans = [
        _make_list_read_plan("t1", d, f"{d}/a.txt", task_text=f"list and read dir={d} file={d}/a.txt"),
        _make_read_plan("t2", f"{d}/b.txt", task_text=f"read path={d}/b.txt"),
    ]
    for p in plans:
        _plan_store_for(tmp_path).save(p)

    assert SkillPromoter(min_recurrence=3).candidates(plans) == []


# ===========================================================================
# 3.  Ignores unstable plans with repairs
# ===========================================================================

def test_ignores_unstable_plans_with_repairs(tmp_path):
    ps = _plan_store_for(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    d = tmp_path.as_posix()
    plans = [
        _make_write_read_plan("t1", f"{d}/a.txt", task_text=f"write file {d}/a.txt then read file {d}/a.txt"),
        _make_write_read_plan("t2", f"{d}/b.txt", task_text=f"write file {d}/b.txt then read file {d}/b.txt"),
        _make_write_read_plan("t3", f"{d}/c.txt", task_text=f"write file {d}/c.txt then read file {d}/c.txt"),
    ]
    for p in plans:
        ps.save(p)
        mem.record("repair_inserted", {"task_id": p.task_id, "repairs": []})

    assert SkillPromoter().candidates(plans, memory=mem) == []


# ===========================================================================
# 4.  Generalization: varying field -> param, constant -> literal
# ===========================================================================

def test_generalization_params_are_varying_fields(tmp_path):
    d = tmp_path.as_posix()
    plans = [
        _make_write_read_plan("t1", f"{d}/a.txt", content="x",
                              task_text=f"write file {d}/a.txt then read file {d}/a.txt"),
        _make_write_read_plan("t2", f"{d}/b.txt", content="x",
                              task_text=f"write file {d}/b.txt then read file {d}/b.txt"),
        _make_write_read_plan("t3", f"{d}/c.txt", content="x",
                              task_text=f"write file {d}/c.txt then read file {d}/c.txt"),
    ]
    for p in plans:
        _plan_store_for(tmp_path).save(p)

    cand = SkillPromoter(min_recurrence=3).candidates(plans)[0]
    assert "path" in cand.params
    assert "content" not in cand.params


# ===========================================================================
# 5.  Ambiguous pattern is rejected
# ===========================================================================

def test_ambiguous_pattern_is_rejected(tmp_path):
    ps = _plan_store_for(tmp_path)
    plans = [
        MultiStepPlan(
            task_id="t1",
            task="write file /a",
            steps=[PlanStep(
                tool="write_file",
                arg=json.dumps({"path": "/a", "content": "x"}),
                reason="write",
                depends_on=[],
                status=StepStatus.DONE,
            )],
        ),
        MultiStepPlan(
            task_id="t2",
            task="write file /b",
            steps=[PlanStep(
                tool="write_file",
                arg=json.dumps({"path": "/b", "content": 42}),
                reason="write",
                depends_on=[],
                status=StepStatus.DONE,
            )],
        ),
        MultiStepPlan(
            task_id="t3",
            task="write file /c",
            steps=[PlanStep(
                tool="write_file",
                arg=json.dumps({"path": "/c", "content": [1, 2, 3]}),
                reason="write",
                depends_on=[],
                status=StepStatus.DONE,
            )],
        ),
    ]
    for p in plans:
        ps.save(p)

    assert SkillPromoter(min_recurrence=3).candidates(plans) == []


# ===========================================================================
# 6.  Candidate renders a valid MultiStepPlan
# ===========================================================================

def test_candidate_renders_valid_multistep_plan(tmp_path):
    d = tmp_path.as_posix()
    plans = [
        _make_list_read_plan("t1", d, f"{d}/a.txt",
                             task_text=f"list and read dir={d} file={d}/a.txt")
    ] * 3
    for p in plans:
        _plan_store_for(tmp_path).save(p)

    cand = SkillPromoter(min_recurrence=3).candidates(plans)[0]
    plan = render_candidate(cand, "render-test")
    assert plan is not None
    assert isinstance(plan, MultiStepPlan)
    assert valid_dag(plan)


# ===========================================================================
# 7.  Successful promotion registers versioned skill
# ===========================================================================

def test_successful_promotion_registers_versioned_skill(tmp_path):
    from aetheris.learning.engine import LearningEngine
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.jsonl"))
    experience = ExperienceStore(str(tmp_path / "experience.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    engine = LearningEngine(mem, str(tmp_path), knowledge, experience, learned)

    skill = SkillTemplate(
        id="",
        name="list_and_read_first",
        description="List a directory then read a named file.",
        trigger_patterns=[r"\blist\s+and\s+read\b.*\bdir="],
        required_params=["dir", "file"],
        steps=[
            SkillStep(
                tool="list_dir",
                arg_template='{"path": "{dir}"}',
                reason="list directory",
                depends_on=[],
            ),
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{file}"}',
                reason="read file",
                depends_on=[0],
            ),
        ],
    )

    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    promoted = engine.promote_skill(skill, reg, workspace_root=str(tmp_path))
    assert promoted is True

    active = reg.active_skills()
    assert len(active) == 1
    registered = active[0]
    assert registered.name == "list_and_read_first"
    assert registered.version == 1

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promoted" in kinds


# ===========================================================================
# 8.  Rejected promotion is not registered
# ===========================================================================

def test_rejected_promotion_is_not_registered(tmp_path):
    from aetheris.evaluation.compare import SkillComparisonResult, SkillCaseResult
    from aetheris.evaluation.cases import WorkflowCase
    from aetheris.learning.engine import LearningEngine
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    engine = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    failing_result = SkillComparisonResult(
        baseline=[SkillCaseResult(name="wf", completed=True)],
        candidate=[SkillCaseResult(name="wf", completed=False)],
    )

    wf_case = WorkflowCase(name="wf", task="test task", skill="bad_skill")

    original_comp = __import__("aetheris.evaluation.compare", fromlist=["SkillComparison"]).SkillComparison
    original_run = original_comp.run

    def mock_run(self, cases, skill=None):
        return failing_result

    original_comp.run = mock_run
    try:
        promoted = engine.promote_skill(
            SkillTemplate(
                id="", name="bad_skill",
                description="Will fail the gate.",
                trigger_patterns=[r"bad\s+skill"], required_params=[],
                steps=[],
            ),
            SkillRegistry(str(tmp_path / "skills.jsonl")),
            cases=[wf_case],
            workspace_root=str(tmp_path),
        )
    finally:
        original_comp.run = original_run

    assert promoted is False
    assert SkillRegistry(str(tmp_path / "skills.jsonl")).active_skills() == []

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promotion_rejected" in kinds


# ===========================================================================
# 9.  Promotion owned by LearningEngine and reversible
# ===========================================================================

def test_promotion_owned_by_learning_engine_and_reversible(tmp_path):
    from aetheris.learning.engine import LearningEngine
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    engine = LearningEngine(
        mem, str(tmp_path),
        KnowledgeStore(str(tmp_path / "knowledge.jsonl")),
        ExperienceStore(str(tmp_path / "experience.jsonl")),
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    skill = SkillTemplate(
        id="",
        name="list_and_read_first",
        description="List a directory then read a named file.",
        trigger_patterns=[r"\blist\s+and\s+read\b.*\bdir="],
        required_params=["dir", "file"],
        steps=[
            SkillStep(
                tool="list_dir",
                arg_template='{"path": "{dir}"}',
                reason="list directory",
                depends_on=[],
            ),
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{file}"}',
                reason="read file",
                depends_on=[0],
            ),
        ],
    )

    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    assert engine.promote_skill(skill, reg, workspace_root=str(tmp_path)) is True

    kinds = [e["kind"] for e in mem.history()]
    assert "skill_promoted" in kinds

    active = reg.active_skills()
    assert len(active) == 1
    skill_id = active[0].id

    assert engine.demote_skill(skill_id, reg, reason="test demotion") is True
    assert reg.match(f"list and read dir={tmp_path.as_posix()} file={tmp_path.as_posix()}/a.txt") is None

    kinds2 = [e["kind"] for e in mem.history()]
    assert "skill_demoted" in kinds2


# ===========================================================================
# 10.  Auto skill runs through safety gate
# ===========================================================================

def test_auto_skill_runs_through_safety_gate(tmp_path):
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    ws = _write_skill()
    reg.register(ws)

    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")

    ex, queue, mem, _, _ = _exec(tmp_path, safe_mode=True, skills=reg)
    d = tmp_path.as_posix()
    rec = queue.enqueue(f"write dst={d}/out.txt content=hello")
    state = _drain(ex, queue, rec.id)

    assert state != TaskState.DONE
    assert state in (TaskState.WAITING_FOR_CONTEXT, TaskState.BLOCKED, TaskState.FAILED)


# ===========================================================================
# 11.  Auto skill matches hand-authored on same workflow
# ===========================================================================

def test_auto_skill_matches_hand_authored_on_same_workflow(tmp_path):
    from aetheris.evaluation.compare import SkillComparison
    from aetheris.evaluation.cases import skill_workflow_suite

    mem = MemoryStore(str(tmp_path / "wf_events.jsonl"))
    comp = SkillComparison(mem, str(tmp_path))

    hand_authored = SkillTemplate(
        id="",
        name="list_and_read_first",
        description="List a directory then read a named file.",
        trigger_patterns=[r"\blist\s+and\s+read\b.*\bdir="],
        required_params=["dir", "file"],
        steps=[
            SkillStep(
                tool="list_dir",
                arg_template='{"path": "{dir}"}',
                reason="list directory",
                depends_on=[],
            ),
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{file}"}',
                reason="read file",
                depends_on=[0],
            ),
        ],
    )

    result = comp.run(skill_workflow_suite(str(tmp_path)), skill=hand_authored)
    assert result.completion_on >= result.completion_off
    assert result.regressed == []


# ===========================================================================
# 12.  No repeated pattern leaves registry unchanged
# ===========================================================================

def test_no_repeated_pattern_leaves_registry_unchanged(tmp_path):
    d = tmp_path.as_posix()
    plans = [
        _make_list_read_plan("t1", d, f"{d}/a.txt", task_text=f"list and read dir={d} file={d}/a.txt"),
        _make_read_plan("t2", f"{d}/b.txt", task_text=f"read path={d}/b.txt"),
    ]
    for p in plans:
        _plan_store_for(tmp_path).save(p)

    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    before_count = len(reg.active_skills())

    SkillPromoter(min_recurrence=3).candidates(plans)

    assert len(reg.active_skills()) == before_count
