"""Tests for Experience-Guided Skill Selection v0.

Canary this round: ``test_experience_guided_off_is_byte_identical``.  If
guided-off ever diverges from Experience v0, re-ranking leaked into a path it
shouldn't touch and the "never worse" floor is broken.
"""

from aetheris.memory import (
    ExperienceMemory,
    Lesson,
    OutcomeType,
    experience_bias,
    experience_rerank,
)
from aetheris.skills.registry import SkillRegistry, SkillTemplate
from aetheris.reasoning.engine import ReasoningEngine
from aetheris.reasoning.schema import Provenance
from aetheris.tools.builtins import default_registry


# ---------------------------------------------------------------------------
# Shared re-ranker core
# ---------------------------------------------------------------------------


def test_experience_bias_directions():
    les_worked = Lesson(
        id="l1", outcome=OutcomeType.WORKED_WELL.value, problem="import repair worked",
        cause="c", fix="f", confidence=0.8,
    )
    les_avoid = Lesson(
        id="l2", outcome=OutcomeType.FAILED_REPEATEDLY.value, problem="import repair flailed",
        cause="c", fix="f", confidence=0.8,
    )
    les_safe = Lesson(
        id="l3", outcome=OutcomeType.FAILED_SAFELY.value, problem="import blocked safely",
        cause="c", fix="f", confidence=0.8,
    )
    # Relevant lessons bias in the right direction.
    assert experience_bias("import repair", [les_worked]) > 0
    assert experience_bias("import repair", [les_avoid]) < 0
    assert experience_bias("import repair", [les_safe]) == 0  # safety floor neutral
    # An irrelevant lesson contributes nothing.
    assert experience_bias("unrelated thing", [les_worked, les_avoid]) == 0


def test_experience_rerank_is_permutation_and_stable():
    options = ["alpha", "beta", "gamma", "delta"]
    # Empty lessons -> identical order (the honest [] floor).
    assert experience_rerank(options, []) == options
    # No lesson overlap -> identical order (no leak).
    les = Lesson(
        id="lx", outcome=OutcomeType.WORKED_WELL.value, problem="totally unrelated",
        cause="c", fix="f", confidence=0.9,
    )
    assert experience_rerank(options, [les], keyfn=lambda o: o) == options
    # Set equality: a permutation, nothing added/removed.
    les2 = Lesson(
        id="ly", outcome=OutcomeType.WORKED_WELL.value, problem="beta recovered",
        cause="c", fix="f", confidence=0.7,
    )
    out = experience_rerank(options, [les2], keyfn=lambda o: o)
    assert set(out) == set(options)
    assert out[0] == "beta"  # the only option the lesson bears on floats up


def test_experience_rerank_never_introduces_or_removes_options():
    options = [1, 2, 3]
    les = Lesson(
        id="lz", outcome=OutcomeType.FAILED_REPEATEDLY.value, problem="option 1 kept dying",
        cause="c", fix="f", confidence=0.9,
    )
    out = experience_rerank(options, [les], keyfn=str)
    assert sorted(out) == [1, 2, 3]


# ---------------------------------------------------------------------------
# CANARY: guided-off == Experience v0 (byte-identical floor)
# ---------------------------------------------------------------------------


def test_experience_guided_off_is_byte_identical(tmp_path):
    # 1) The re-ranker itself: no confident lessons -> exact base order.
    base = ["s1", "s2", "s3"]
    off = ExperienceMemory(str(tmp_path / "lessons_off.jsonl"), consume_enabled=False)
    assert experience_rerank(base, off.query(), keyfn=lambda o: o) == base

    # 2) Skill selection: experience handle present but consumption OFF must
    #    match the no-handle selection exactly.
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    reg.register(SkillTemplate(
        id="sk_alpha", name="alpha", description="d",
        trigger_patterns=["list"], required_params=[], steps=[],
    ))
    reg.register(SkillTemplate(
        id="sk_beta", name="beta", description="d",
        trigger_patterns=["list"], required_params=[], steps=[],
    ))
    task = "list the directory"
    no_handle = reg.match(task)
    with_handle = reg.match(task, experience=off)
    assert no_handle[0].name == with_handle[0].name

    # 3) Reasoning: an experience handle with consumption OFF adds zero
    #    observations, so the deliberation is identical to no handle.
    skills = default_registry()
    r_off = ReasoningEngine(skills=skills, experience=off)
    r_none = ReasoningEngine(skills=skills)
    ctx = type("Ctx", (), {"task": task, "understanding_facts": {}, "candidate_shapes": ("a", "b")})()
    d_off = r_off.deliberate_for_planning(ctx)
    d_none = r_none.deliberate_for_planning(ctx)
    assert d_off.seam == d_none.seam
    assert d_off.recommendation == d_none.recommendation
    assert d_off.recommended_approach == d_none.recommended_approach
    assert d_off.abstained == d_none.abstained
    assert round(d_off.confidence, 6) == round(d_none.confidence, 6)


# ---------------------------------------------------------------------------
# Seam 1: SkillRegistry.match re-ranks by experience
# ---------------------------------------------------------------------------


def _build_reg(tmp_path):
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    reg.register(SkillTemplate(
        id="sk_alpha", name="alpha", description="d",
        trigger_patterns=["list"], required_params=[], steps=[],
    ))
    reg.register(SkillTemplate(
        id="sk_beta", name="beta", description="d",
        trigger_patterns=["list"], required_params=[], steps=[],
    ))
    return reg


def test_skill_match_reranks_toward_worked_well(tmp_path):
    reg = _build_reg(tmp_path)
    exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    exp.record(
        OutcomeType.WORKED_WELL, problem="beta recovered the import",
        cause="c", fix="f", confidence=0.9,
    )
    chosen = reg.match("list the directory", experience=exp)
    assert chosen[0].name == "beta"


def test_skill_match_reranks_away_from_failed_repeatedly(tmp_path):
    reg = _build_reg(tmp_path)
    exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    exp.record(
        OutcomeType.FAILED_REPEATEDLY, problem="alpha kept dying on import",
        cause="c", fix="f", confidence=0.9,
    )
    # alpha sinks; beta (neutral) wins the first slot.
    chosen = reg.match("list the directory", experience=exp)
    assert chosen[0].name == "beta"


# ---------------------------------------------------------------------------
# Seam 2: Reasoning gets experience only as Observations
# ---------------------------------------------------------------------------


def test_reasoning_experience_observation_provenance(tmp_path):
    exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    exp.record(
        OutcomeType.WORKED_WELL, problem="import repair worked well",
        cause="c", fix="f", confidence=0.8,
    )
    r = ReasoningEngine(skills=default_registry(), experience=exp)
    ctx = type("Ctx", (), {"task": "fix import", "understanding_facts": {}, "candidate_shapes": ("a", "b")})()
    d = r.deliberate_for_planning(ctx)
    sources = {o.provenance.source for o in d.observations}
    assert "experience" in sources
    exp_obs = [o for o in d.observations if o.provenance.source == "experience"]
    assert exp_obs and all(isinstance(o.provenance, Provenance) for o in exp_obs)
    assert all(o.provenance.source == "experience" for o in exp_obs)


def test_reasoning_experience_off_adds_no_observations(tmp_path):
    exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=False)
    exp.record(OutcomeType.WORKED_WELL, problem="import repair worked", cause="c", fix="f")
    r = ReasoningEngine(skills=default_registry(), experience=exp)
    ctx = type("Ctx", (), {"task": "fix import", "understanding_facts": {}, "candidate_shapes": ("a", "b")})()
    d = r.deliberate_for_planning(ctx)
    assert all(o.provenance.source != "experience" for o in d.observations)


# ---------------------------------------------------------------------------
# Seam 3: Learning can only get MORE conservative (HOLD)
# ---------------------------------------------------------------------------


def test_learning_holds_on_experience_failure(tmp_path, monkeypatch):
    from aetheris.memory.experience import ExperienceStore
    from aetheris.memory.knowledge import KnowledgeStore
    from aetheris.memory.learned import LearnedKeywordStore
    from aetheris.memory.store import MemoryStore
    from aetheris.learning.engine import LearningEngine, Candidate

    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "know.jsonl"))
    experience = ExperienceStore(str(tmp_path / "exp.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    exp_lessons = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    exp_lessons.record(
        OutcomeType.FAILED_REPEATEDLY, problem="write content kept failing",
        cause="c", fix="f", confidence=0.9,
    )

    eng = LearningEngine(mem, str(tmp_path), knowledge, experience, learned, experience_lessons=exp_lessons)

    # Force a candidate whose intent/keyword the avoid-lesson bears on.
    monkeypatch.setattr(eng, "propose_one", lambda cases: Candidate("write", "content", "case_x"))

    class _StubReport:
        pass_rate = 1.0
        results = []

    class _StubEval:
        def __init__(self, *a, **k):
            pass

        def run(self, cases):
            return _StubReport()

    monkeypatch.setattr("aetheris.learning.engine.Evaluator", _StubEval)

    res = eng.attempt([])
    assert res.accepted is False
    assert "experience" in res.reason.lower()
    # The learned store must be untouched — experience only holds, never adopts.
    assert learned.as_keywords() == {}
