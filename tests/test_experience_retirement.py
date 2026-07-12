"""Tests for Experience-Guided Retirement v0.

Canary: ``test_experience_guided_retirement_off_is_byte_identical``.  With
consumption off (or no experience handle), retirement retires nothing and the
skill library is unchanged — the promotion-only floor.  The other properties
this milestone must hold: retirement is *bounded* (a lone weak failure can't
retire a skill) and *reversible* (a tombstone can be walked back).
"""
from aetheris.learning.engine import LearningEngine
from aetheris.memory import ExperienceMemory, OutcomeType
from aetheris.memory.experience import ExperienceStore
from aetheris.learning.experience_retire import ExperienceGuidedRetirer
from aetheris.memory.knowledge import KnowledgeStore
from aetheris.memory.learned import LearnedKeywordStore
from aetheris.memory.store import MemoryStore
from aetheris.skills.registry import SkillRegistry, SkillTemplate


def _reg(tmp_path):
    reg = SkillRegistry(str(tmp_path / "skills.jsonl"))
    reg.register(SkillTemplate(
        id="sk_imp", name="importerrorfix", description="d",
        trigger_patterns=["fix importerror"], required_params=[], steps=[],
    ))
    return reg


def _exp(tmp_path, consume=True):
    return ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=consume)


# ---------------------------------------------------------------------------
# CANARY: guided-off == Experience v0 (promotion-only floor)
# ---------------------------------------------------------------------------


def test_experience_guided_retirement_off_is_byte_identical(tmp_path):
    reg = _reg(tmp_path)
    # Experience present but consumption OFF -> query() returns [] -> no retirement.
    off = _exp(tmp_path, consume=False)
    off.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix kept failing", cause="c", fix="f", confidence=0.9)

    assert ExperienceGuidedRetirer(off).candidates_for_retirement(reg) == []
    assert ExperienceGuidedRetirer(off).retire_stale(reg) == []
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]

    # Via the LearningEngine seam as well.
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "know.jsonl"))
    experience = ExperienceStore(str(tmp_path / "exp.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    eng = LearningEngine(mem, str(tmp_path), knowledge, experience, learned, experience_lessons=off)
    assert eng.retire_stale_skills(reg) == []
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]


# ---------------------------------------------------------------------------
# Bounded: a lone weak failure cannot retire; sustained/confident avoidance can
# ---------------------------------------------------------------------------


def test_retirement_is_bounded_against_single_weak_failure(tmp_path):
    reg = _reg(tmp_path)
    exp = _exp(tmp_path)
    # One low-confidence avoid lesson -> bias -0.5, above the -0.6 threshold.
    exp.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix failed once", cause="c", fix="f", confidence=0.5)
    assert ExperienceGuidedRetirer(exp).candidates_for_retirement(reg) == []
    assert ExperienceGuidedRetirer(exp).retire_stale(reg) == []
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]


def test_retirement_triggers_on_confident_avoidance(tmp_path):
    reg = _reg(tmp_path)
    exp = _exp(tmp_path)
    # Confident avoid lesson -> bias -0.9 <= -0.6 threshold.
    exp.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix kept failing repeatedly", cause="c", fix="f", confidence=0.9)
    cands = ExperienceGuidedRetirer(exp).candidates_for_retirement(reg)
    assert [cid for cid, _, _ in cands] == ["sk_imp"]
    assert ExperienceGuidedRetirer(exp).retire_stale(reg) == ["sk_imp"]
    assert [s.name for s in reg.active_skills()] == []


def test_retirement_balances_worked_well_against_avoidance(tmp_path):
    reg = _reg(tmp_path)
    exp = _exp(tmp_path)
    # A worked_well lesson offsets the avoid lesson -> net bias ~0 -> no retire.
    exp.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix kept failing", cause="c", fix="f", confidence=0.8)
    exp.record(OutcomeType.WORKED_WELL, problem="importerrorfix recovered after repair", cause="c", fix="f", confidence=0.8)
    assert ExperienceGuidedRetirer(exp).candidates_for_retirement(reg) == []
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]


# ---------------------------------------------------------------------------
# Reversible: a tombstone can be walked back
# ---------------------------------------------------------------------------


def test_experience_guided_retirement_is_reversible(tmp_path):
    reg = _reg(tmp_path)
    exp = _exp(tmp_path)
    exp.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix kept failing", cause="c", fix="f", confidence=0.9)
    retirer = ExperienceGuidedRetirer(exp)

    # Retire.
    assert retirer.retire_stale(reg) == ["sk_imp"]
    assert reg.get("sk_imp").active is False
    assert [s.name for s in reg.active_skills()] == []

    # Reverse.
    assert retirer.restore("sk_imp", reg) is True
    assert reg.get("sk_imp").active is True
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]


def test_learning_retire_and_restore_roundtrip(tmp_path):
    reg = _reg(tmp_path)
    exp = _exp(tmp_path)
    exp.record(OutcomeType.FAILED_REPEATEDLY, problem="importerrorfix kept failing", cause="c", fix="f", confidence=0.9)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "know.jsonl"))
    experience = ExperienceStore(str(tmp_path / "exp.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    eng = LearningEngine(mem, str(tmp_path), knowledge, experience, learned, experience_lessons=exp)

    assert eng.retire_stale_skills(reg) == ["sk_imp"]
    assert reg.get("sk_imp").active is False
    assert eng.restore_retired_skill("sk_imp", reg) is True
    assert reg.get("sk_imp").active is True


def test_learning_retire_noop_without_experience_handle(tmp_path):
    reg = _reg(tmp_path)
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "know.jsonl"))
    experience = ExperienceStore(str(tmp_path / "exp.jsonl"))
    learned = LearnedKeywordStore(str(tmp_path / "learned.jsonl"))
    eng = LearningEngine(mem, str(tmp_path), knowledge, experience, learned)  # no experience_lessons
    assert eng.retire_stale_skills(reg) == []
    assert [s.name for s in reg.active_skills()] == ["importerrorfix"]
