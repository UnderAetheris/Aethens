
from aetheris.evaluation.cases import EvalCase
from aetheris.learning.engine import LearningEngine
from aetheris.memory.experience import ExperienceStore
from aetheris.memory.knowledge import KnowledgeStore
from aetheris.memory.learned import LearnedKeywordStore
from aetheris.memory.store import MemoryStore


def test_learning_engine_accepts_new_keyword_and_improves(tmp_path):
    memory = MemoryStore(str(tmp_path / "memory.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.jsonl"))
    experience = ExperienceStore(str(tmp_path / "experience.jsonl"))
    engine = LearningEngine(
        memory,
        str(tmp_path),
        knowledge,
        experience,
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    cases = [
        EvalCase(
            name="list_with_unknown_verb",
            task="scan path={root}",
            expected_tool="list_dir",
        )
    ]

    result = engine.attempt(cases)

    assert result.accepted is True
    assert result.candidate is not None
    assert result.candidate.intent == "list"
    assert result.candidate.keyword == "scan"
    assert engine.extra_keywords["list"] == ["scan"]
    assert knowledge.all(), "knowledge should record the accepted lesson"
    assert experience.all(), "experience should record the failed case and attempt"


def test_learning_engine_rejects_when_no_candidate(tmp_path):
    memory = MemoryStore(str(tmp_path / "memory.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.jsonl"))
    experience = ExperienceStore(str(tmp_path / "experience.jsonl"))
    engine = LearningEngine(
        memory,
        str(tmp_path),
        knowledge,
        experience,
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    cases = [
        EvalCase(name="known_echo", task="hello there", expected_tool="echo"),
    ]

    result = engine.attempt(cases)

    assert result.accepted is False
    assert result.candidate is None
    assert result.reason == "no bounded candidate available"


def test_learning_engine_persists_and_reverts_keywords(tmp_path):
    memory = MemoryStore(str(tmp_path / "memory.jsonl"))
    knowledge = KnowledgeStore(str(tmp_path / "knowledge.jsonl"))
    experience = ExperienceStore(str(tmp_path / "experience.jsonl"))
    engine = LearningEngine(
        memory,
        str(tmp_path),
        knowledge,
        experience,
        LearnedKeywordStore(str(tmp_path / "learned.jsonl")),
    )

    cases = [
        EvalCase(
            name="list_with_unknown_verb",
            task="scan path={root}",
            expected_tool="list_dir",
        )
    ]

    result = engine.attempt(cases)
    assert result.accepted is True
    assert engine.extra_keywords == {"list": ["scan"]}

    assert engine.revert_last() is not None
    assert engine.extra_keywords == {}
