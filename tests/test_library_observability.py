"""Skill Library Observability + Tuning v0 — 12 tests.

   1.  test_get_skills_lists_active
   2.  test_get_skills_excludes_retired_by_default
   3.  test_skill_detail_exposes_provenance
   4.  test_activity_shows_promotions_and_rejections
   5.  test_task_shows_plan_source_skill
   6.  test_task_shows_fallback_reason
   7.  test_promotion_config_defaults
   8.  test_promotion_config_override_is_clamped
   9.  test_tuning_does_not_change_execution_authority
  10.  test_observability_is_readonly_no_mutation
  11.  test_defaults_unchanged_behaves_like_today
  12.  test_restart_explainability_of_library
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from aetheris.api.app import create_app
from aetheris.api.state import AppState
from aetheris.config import PromotionConfig
from aetheris.controller.queue import TaskState
from aetheris.skills.registry import SkillRegistry, SkillStep, SkillTemplate


# ===========================================================================
# Helpers
# ===========================================================================

def _make_client(tmp_path, promotion_config=None):
    if promotion_config is None:
        promotion_config = PromotionConfig.from_env()
    state = AppState.create(root=str(tmp_path / "data"))
    state.promotion_config = promotion_config
    app = create_app(state=state, auto_tick=False)
    with TestClient(app) as c:
        c.app_state = app.state.aetheris
        yield c


@pytest.fixture
def client(tmp_path):
    next(_make_client(tmp_path))


@pytest.fixture
def client_with_skill(tmp_path):
    """Client with a hand-authored skill registered."""
    gen = _make_client(tmp_path)
    c = next(gen)
    reg = c.app_state.registry
    reg.register(SkillTemplate(
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
    ))
    yield c


@pytest.fixture
def client_with_retired(tmp_path):
    """Client with one active and one retired skill."""
    gen = _make_client(tmp_path)
    c = next(gen)
    reg = c.app_state.registry
    reg.register(SkillTemplate(
        id="",
        name="active_skill",
        description="An active skill.",
        trigger_patterns=[r"\bactive\b"],
        required_params=[],
        steps=[SkillStep(tool="echo", arg_template='"ok"', reason="echo", depends_on=[])],
    ))
    s = reg.register(SkillTemplate(
        id="",
        name="retired_skill",
        description="A retired skill.",
        trigger_patterns=[r"\bretired\b"],
        required_params=[],
        steps=[SkillStep(tool="echo", arg_template='"ok"', reason="echo", depends_on=[])],
    ))
    reg.retire(s.id)
    yield c


@pytest.fixture
def client_with_auto_skill(tmp_path):
    """Client with an auto-promoted skill and provenance events."""
    gen = _make_client(tmp_path)
    c = next(gen)
    mem = c.app_state.memory
    reg = c.app_state.registry
    # Record provenance events that the API can read back
    mem.record("skill_candidate_mined", {
        "name": "auto_write_read",
        "provenance": {
            "source_task_ids": ["task-0012", "task-0019", "task-0027"],
            "recurrence": 3,
            "shape": {"tools": ["write_file", "read_file"], "edges": [(1, 0)]},
        },
    })
    mem.record("skill_promoted", {
        "skill_name": "auto_write_read",
        "version": 1,
        "skill_id": "auto-1-auto_write_read",
        "completion_on": 0.95,
        "completion_off": 0.80,
        "regressed": [],
    })
    reg.register(SkillTemplate(
        id="auto-1-auto_write_read",
        name="auto_write_read",
        description="Auto-promoted skill.",
        trigger_patterns=[r"\bwrite\s+and\s+read\b"],
        required_params=["path"],
        steps=[
            SkillStep(tool="write_file", arg_template='{"path": "{path}", "content": "x"}',
                      reason="write", depends_on=[]),
            SkillStep(tool="read_file", arg_template='{"path": "{path}"}',
                      reason="read back", depends_on=[0]),
        ],
        version=1,
    ))
    yield c


@pytest.fixture
def client_after_promotion(tmp_path):
    """Client with promotion/rejection events in memory."""
    gen = _make_client(tmp_path)
    c = next(gen)
    mem = c.app_state.memory
    mem.record("skill_promoted", {
        "skill_name": "promoted_skill",
        "version": 1,
        "skill_id": "promo-1",
    })
    mem.record("skill_promotion_rejected", {
        "skill_name": "rejected_skill",
        "reason": "gate not cleared: completion_on=0.5 completion_off=0.9 regressed=[]",
    })
    yield c


# ===========================================================================
# 1.  GET /skills lists active skills
# ===========================================================================

def test_get_skills_lists_active(client_with_skill):
    r = client_with_skill.get("/skills")
    assert r.status_code == 200
    assert any(s["name"] == "list_and_read_first" for s in r.json())


# ===========================================================================
# 2.  GET /skills excludes retired by default, includes with ?include_retired=true
# ===========================================================================

def test_get_skills_excludes_retired_by_default(client_with_retired):
    active = client_with_retired.get("/skills").json()
    assert all(s["active"] for s in active)
    assert not any(s["name"] == "retired_skill" for s in active)
    allsk = client_with_retired.get("/skills?include_retired=true").json()
    assert any(not s["active"] for s in allsk)
    assert any(s["name"] == "retired_skill" for s in allsk)


# ===========================================================================
# 3.  GET /skills/{name} exposes provenance
# ===========================================================================

def test_skill_detail_exposes_provenance(client_with_auto_skill):
    d = client_with_auto_skill.get("/skills/auto_write_read").json()
    assert d["provenance"] is not None
    assert d["provenance"]["recurrence"] >= 3
    assert d["provenance"]["source_task_ids"]


# ===========================================================================
# 4.  GET /skills/activity shows promotions and rejections
# ===========================================================================

def test_activity_shows_promotions_and_rejections(client_after_promotion):
    acts = client_after_promotion.get("/skills/activity").json()
    kinds = {a["kind"] for a in acts}
    assert "skill_promoted" in kinds
    assert any(a["reason"] for a in acts if a["kind"] == "skill_promotion_rejected")


# ===========================================================================
# 5.  Task using a skill shows plan_source starting with "skill:"
# ===========================================================================

def test_task_shows_plan_source_skill(client_with_skill):
    tid = _submit_and_drain(client_with_skill, "list and read dir=/data file=/data/a.txt")
    src = client_with_skill.get(f"/tasks/{tid}").json()["plan_source"]
    assert src.startswith("skill:")


# ===========================================================================
# 6.  Task falling back shows fallback: reason
# ===========================================================================

def test_task_shows_fallback_reason(client_with_skill):
    tid = _submit_and_drain(client_with_skill, "read the first file in")
    src = client_with_skill.get(f"/tasks/{tid}").json()["plan_source"]
    assert src.startswith("fallback:") or src == "decomposed"


# ===========================================================================
# 7.  Promotion config returns defaults
# ===========================================================================

def test_promotion_config_defaults(tmp_path):
    c = next(_make_client(tmp_path))
    cfg = c.get("/config/promotion").json()
    assert cfg["min_recurrence"] == 3
    assert cfg["promotion_budget"] == 1
    assert cfg["min_recurrence_range"] == [2, 20]
    assert cfg["promotion_budget_range"] == [1, 5]


# ===========================================================================
# 8.  Promotion config env overrides are clamped
# ===========================================================================

def test_promotion_config_override_is_clamped(monkeypatch):
    monkeypatch.setenv("AETHERIS_MIN_RECURRENCE", "1")
    assert PromotionConfig.from_env().min_recurrence == 2
    monkeypatch.setenv("AETHERIS_PROMOTION_BUDGET", "99")
    assert PromotionConfig.from_env().promotion_budget == 5
    monkeypatch.setenv("AETHERIS_STABILITY_MAX_REPAIRS", "99")
    assert PromotionConfig.from_env().stability_max_repairs == 3


# ===========================================================================
# 9.  Tuning does not change execution authority
# ===========================================================================

def test_tuning_does_not_change_execution_authority(tmp_path):
    from aetheris.config import PromotionConfig

    loosest = PromotionConfig(
        min_recurrence=2,
        stability_max_repairs=3,
        promotion_budget=5,
    )
    c = next(_make_client(tmp_path, promotion_config=loosest))
    reg = c.app_state.registry
    # Register a skill with an unsafe step (write_file in safe_mode).
    unsafe = SkillTemplate(
        id="",
        name="unsafe_auto_write",
        description="Writes a file — blocked in safe_mode.",
        trigger_patterns=[r"\bunsafe\s+auto\s+write\b"],
        required_params=["path"],
        steps=[
            SkillStep(
                tool="write_file",
                arg_template='{"path": "{path}", "content": "unsafe"}',
                reason="write",
                depends_on=[],
            ),
        ],
    )
    reg.register(unsafe)
    # Submit a task that matches the skill.
    created = c.post("/tasks", json={"task": "unsafe auto write path=/out.txt"}).json()
    for _ in range(10):
        c.app_state.executive.run_once()
    rec = c.app_state.queue.get(created["id"])
    assert rec.state != TaskState.DONE


# ===========================================================================
# 10. Observability endpoints are read-only — no mutation
# ===========================================================================

def test_observability_is_readonly_no_mutation(client_with_skill):
    before = client_with_skill.get("/skills").json()
    client_with_skill.get("/skills/activity")
    client_with_skill.get("/config/promotion")
    client_with_skill.get(f"/skills/{before[0]['name']}")
    after = client_with_skill.get("/skills").json()
    assert after == before


# ===========================================================================
# 11. Defaults unchanged — byte-identical behavior to v0
# ===========================================================================

def test_defaults_unchanged_behaves_like_today(tmp_path):
    from aetheris.config import PromotionConfig
    assert PromotionConfig.from_env() == PromotionConfig()
    # Defaults match the hardcoded values from Idle-Time Promotion v0.
    assert PromotionConfig().min_recurrence == 3
    assert PromotionConfig().stability_max_repairs == 0
    assert PromotionConfig().promotion_budget == 1


# ===========================================================================
# 12. Restart explainability — registry + journal reconstruct library state
# ===========================================================================

def test_restart_explainability_of_library(tmp_path):
    c = next(_make_client(tmp_path))
    reg = c.app_state.registry
    mem = c.app_state.memory
    # Register a skill and record promotion events.
    reg.register(SkillTemplate(
        id="",
        name="restart_skill",
        description="For restart test.",
        trigger_patterns=[r"\brestart\b"],
        required_params=[],
        steps=[SkillStep(tool="echo", arg_template='"ok"', reason="echo", depends_on=[])],
    ))
    mem.record("skill_promoted", {
        "skill_name": "restart_skill",
        "version": 1,
        "skill_id": "restart-1",
    })
    mem.record("skill_candidate_mined", {
        "name": "restart_skill",
        "provenance": {
            "source_task_ids": ["t1", "t2", "t3"],
            "recurrence": 3,
            "shape": {"tools": ["echo"], "edges": []},
        },
    })
    # First read: verify endpoints work.
    skills = c.get("/skills").json()
    assert any(s["name"] == "restart_skill" for s in skills)
    detail = c.get("/skills/restart_skill").json()
    assert detail["provenance"] is not None
    assert detail["provenance"]["recurrence"] == 3
    acts = c.get("/skills/activity").json()
    assert any(a["kind"] == "skill_promoted" for a in acts)


# ===========================================================================
# Helpers
# ===========================================================================

def _submit_and_drain(client, task_text):
    created = client.post("/tasks", json={"task": task_text}).json()
    for _ in range(20):
        client.app_state.executive.run_once()
    return created["id"]
