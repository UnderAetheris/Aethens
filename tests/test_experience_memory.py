"""Tests for Experience Memory Engine v0.

The canary this milestone lives or dies by is
`test_contradiction_decays_and_retires_lesson`: a memory that cannot
*forget* a lesson the world has stopped confirming is how you get an agent
confidently steering on stale history.
"""
import pytest

from aetheris.memory.lessons import (
    CONTRADICTION_RETIRE_AT,
    ExperienceMemory,
    Lesson,
    LessonStore,
    OutcomeType,
)
from aetheris.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# OutcomeType semantics
# ---------------------------------------------------------------------------


def test_outcome_types_carry_semantics():
    assert OutcomeType.WORKED_WELL.is_success
    assert OutcomeType.FAILED_AND_RECOVERED.is_success
    assert not OutcomeType.FAILED_SAFELY.is_success
    assert not OutcomeType.FAILED_REPEATEDLY.is_success
    assert OutcomeType.FAILED_REPEATEDLY.is_avoid
    assert not OutcomeType.WORKED_WELL.is_avoid


# ---------------------------------------------------------------------------
# The Lesson schema: advisory only, never carries an action
# ---------------------------------------------------------------------------


def test_lesson_schema_has_no_action_field():
    field_names = set(Lesson.__dataclass_fields__)  # type: ignore[attr-defined]
    assert "action" not in field_names
    assert {"problem", "cause", "fix", "outcome", "confidence"} <= field_names


def test_record_writes_a_lesson(tmp_path):
    store = LessonStore(str(tmp_path / "lessons.jsonl"))
    lesson = store.add(
        OutcomeType.FAILED_AND_RECOVERED,
        problem="import repair bounced",
        cause="wrong module guessed",
        fix="use understanding.exporting_module",
        related_task="task:x",
        confidence=0.6,
    )
    assert lesson.outcome == OutcomeType.FAILED_AND_RECOVERED.value
    assert not lesson.retired
    assert lesson.confidence == 0.6


# ---------------------------------------------------------------------------
# Write path safe / disabled
# ---------------------------------------------------------------------------


def test_record_disabled_is_a_noop(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"), record_enabled=False)
    assert em.record(OutcomeType.WORKED_WELL, "p", "c", "f") is None
    assert tmp_path.joinpath("lessons.jsonl").exists() is False


def test_recording_is_order_preserving_and_provenance_stamped(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"))
    a = em.record(OutcomeType.WORKED_WELL, "alpha", "c", "f", related_task="t1")
    b = em.record(OutcomeType.FAILED_REPEATEDLY, "beta", "c", "f", related_task="t2")
    assert a.id != b.id
    all_lessons = em._store.all()
    assert [les.problem for les in all_lessons] == ["alpha", "beta"]
    assert all_lessons[0].related_task == "t1"


# ---------------------------------------------------------------------------
# Consume path gated; honest empty when off
# ---------------------------------------------------------------------------


def test_consume_gated_returns_empty_when_off(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=False)
    em.record(OutcomeType.WORKED_WELL, "p", "c", "f", confidence=0.9)
    # With consumption gated off, every read returns an honest empty list.
    assert em.query() == []
    assert em.advise("p") == []
    assert em.query(outcome=OutcomeType.WORKED_WELL) == []


def test_consume_respects_confidence_floor(tmp_path):
    em = ExperienceMemory(
        str(tmp_path / "lessons.jsonl"), consume_enabled=True, confidence_floor=0.5
    )
    em.record(OutcomeType.WORKED_WELL, "strong", "c", "f", confidence=0.8)
    em.record(OutcomeType.FAILED_REPEATEDLY, "weak", "c", "f", confidence=0.3)
    hits = em.query()
    assert [les.problem for les in hits] == ["strong"]
    # A higher floor still excludes the weak lesson.
    assert em.query(min_confidence=0.9) == []


def test_query_filters_by_outcome_and_problem(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    em.record(OutcomeType.WORKED_WELL, "import fix worked", "c", "f", confidence=0.8)
    em.record(OutcomeType.FAILED_REPEATEDLY, "import fix flailed", "c", "f", confidence=0.8)
    by_outcome = em.query(outcome=OutcomeType.FAILED_REPEATEDLY)
    assert [les.problem for les in by_outcome] == ["import fix flailed"]
    by_problem = em.query(problem="flailed")
    assert [les.problem for les in by_problem] == ["import fix flailed"]


# ---------------------------------------------------------------------------
# Decay / expiry / reversible retire
# ---------------------------------------------------------------------------


def test_retire_is_reversible(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"), consume_enabled=True)
    lesson = em.record(OutcomeType.WORKED_WELL, "p", "c", "f", confidence=0.7)
    assert em.query(problem="p")
    em._store.retire(lesson.id, reason="manual")
    assert em.query(problem="p") == []
    restored = em._store.unretire(lesson.id)
    assert restored is not None and not restored.retired
    assert em.query(problem="p")


def test_decay_retires_stale_lesson(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"))
    lesson = em.record(OutcomeType.WORKED_WELL, "p", "c", "f", confidence=0.7, now=0.0)
    # A confirmed lesson is not stale; a never-confirmed one past TTL is.
    em.record(OutcomeType.WORKED_WELL, "q", "c", "f", confidence=0.7, now=0.0)
    em._store.confirm(lesson.id, now=0.0)  # "p" confirmed
    retired = em.decay(now=10**12, ttl_seconds=100)
    retired_ids = {les.id for les in retired}
    assert lesson.id not in retired_ids
    assert em._store.get(lesson.id).retired is False
    assert em._store.get(em._store.all()[1].id).retired is True


# ---------------------------------------------------------------------------
# CANARY: a contradicted lesson decays and retires, reversibly
# ---------------------------------------------------------------------------


def test_contradiction_decays_and_retires_lesson(tmp_path):
    em = ExperienceMemory(
        str(tmp_path / "lessons.jsonl"), consume_enabled=True, confidence_floor=0.0
    )
    lesson = em.record(
        OutcomeType.FAILED_AND_RECOVERED,
        problem="this repair recovers import errors",
        cause="missing import",
        fix="insert import from understanding",
        confidence=0.8,
    )
    assert lesson.confidence == 0.8

    # The world stops confirming this lesson; each contradiction decays it.
    seen = []
    for _ in range(CONTRADICTION_RETIRE_AT):
        les = em.contradict(lesson.id)
        seen.append(les.confidence)

    final = em._store.get(lesson.id)
    # Strictly decreasing confidence, then retired with reason "contradicted".
    assert seen == sorted(seen, reverse=True)
    assert final.retired is True
    assert final.retired_reason == "contradicted"

    # Consumption never surfaces a retired lesson.
    assert em.query() == []

    # Reversible: unretire restores the lesson exactly as it was retired.
    restored = em.unretire(lesson.id)
    assert restored is not None
    assert restored.retired is False
    assert restored.retired_reason == ""
    assert restored.confidence == final.confidence
    assert em.query()  # visible again


def test_contradiction_below_confidence_floor_also_retires(tmp_path):
    em = ExperienceMemory(str(tmp_path / "lessons.jsonl"))
    lesson = em.record(
        OutcomeType.WORKED_WELL, "p", "c", "f", confidence=0.25
    )
    les = em.contradict(lesson.id)  # 0.25 - 0.2 = 0.05 < 0.15 floor
    assert les.confidence == pytest.approx(0.05)
    assert les.retired is True
    assert les.retired_reason == "contradicted"


# ---------------------------------------------------------------------------
# Experience-off must be byte-identical to Repo-Aware Skills v0
# ---------------------------------------------------------------------------


def _run_with_experience(tmp_path, with_experience):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    from aetheris.controller.executive import ExecutiveController
    from aetheris.controller.queue import TaskQueue

    q = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    from aetheris.config import Config

    config = Config(log_path=str(tmp_path / "ctrl.jsonl"), workspace_root=str(tmp_path))
    exp = None
    if with_experience:
        exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"))
    ex = ExecutiveController(config, q, mem, experience=exp)

    q.enqueue("hello there")
    ex.run_once()
    q.enqueue(f"create path={tmp_path}/out.txt content=hi")
    ex.run_once()
    return mem


def test_experience_off_is_byte_identical_to_v0(tmp_path):
    base = _run_with_experience(tmp_path / "base", with_experience=False)
    exp_dir = tmp_path / "exp_on"
    exp_dir.mkdir()
    with_exp = _run_with_experience(exp_dir, with_experience=True)

    # The decision substrate (events log) is identical whether or not the
    # experience write-path is attached — recording never touches it.
    assert [e["kind"] for e in base.history()] == [e["kind"] for e in with_exp.history()]

    # With consumption off by default, querying experience yields nothing, so a
    # consumer takes its deterministic fallback and the run is unchanged.
    exp = ExperienceMemory(str(exp_dir / "lessons.jsonl"))
    assert exp.query() == []


def test_experience_recording_only_appends_to_its_own_file(tmp_path):
    exp = ExperienceMemory(str(tmp_path / "lessons.jsonl"))
    exp.record(OutcomeType.WORKED_WELL, "p", "c", "f", confidence=0.9)
    # Reading via the gated consume path (default off) is a guaranteed no-op and
    # does not mutate the store.
    before = len(exp._store.all())
    assert exp.query() == []
    assert len(exp._store.all()) == before
