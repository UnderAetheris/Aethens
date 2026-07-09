from aetheris.evaluation.cases import EvalCase
from aetheris.learning.engine import LearningEngine
from aetheris.memory.experience import ExperienceStore
from aetheris.memory.knowledge import KnowledgeStore
from aetheris.memory.learned import LearnedKeywordStore
from aetheris.memory.store import MemoryStore
from aetheris.planner.planner import Planner


def _paths(tmp_path):
    return {
        "events": str(tmp_path / "events.jsonl"),
        "know": str(tmp_path / "know.jsonl"),
        "exp": str(tmp_path / "exp.jsonl"),
        "learned": str(tmp_path / "learned.jsonl"),
    }


def _engine(tmp_path, p):
    return LearningEngine(
        MemoryStore(p["events"]),
        str(tmp_path),
        KnowledgeStore(p["know"]),
        ExperienceStore(p["exp"]),
        LearnedKeywordStore(p["learned"]),
    )


def _cases(tmp_path):
    return [
        EvalCase(name="chat", task="hello", expected_tool="echo"),
        EvalCase(
            name="learnable_write",
            task=f"append path={tmp_path}/o.txt content=hi",
            expected_tool="write_file",
        ),
    ]


def test_accepted_keyword_is_persisted(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    result = engine.attempt(_cases(tmp_path))
    assert result.accepted
    steps = LearnedKeywordStore(p["learned"]).steps()
    assert len(steps) == 1 and steps[0].intent == "write"


def test_planner_loads_persisted_keywords_on_boot(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    engine.attempt(_cases(tmp_path))
    learned_word = engine.extra_keywords["write"][0]
    planner = Planner(learned_store_path=p["learned"])
    plan = planner.plan(f"{learned_word} path={tmp_path}/x.txt content=hi")
    assert plan.tool == "write_file"


def test_state_survives_simulated_restart(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    engine.attempt(_cases(tmp_path))
    before = engine.extra_keywords
    engine2 = _engine(tmp_path, p)
    assert engine2.extra_keywords == before


def test_revert_last_removes_most_recent_keyword(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    engine.attempt(_cases(tmp_path))
    assert engine.extra_keywords.get("write")
    removed = engine.revert_last()
    assert removed is not None and removed.intent == "write"
    assert not engine.extra_keywords.get("write")
    assert not _engine(tmp_path, p).extra_keywords.get("write")


def test_revert_last_is_audit_logged(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    engine.attempt(_cases(tmp_path))
    engine.revert_last()
    kinds = [e["kind"] for e in MemoryStore(p["events"]).history()]
    assert "learning_reverted" in kinds


def test_revert_last_on_empty_is_noop(tmp_path):
    p = _paths(tmp_path)
    engine = _engine(tmp_path, p)
    assert engine.revert_last() is None


def test_prior_passing_behavior_preserved(tmp_path):
    planner = Planner()
    assert planner.plan("hello there").tool == "echo"
    assert planner.plan(f"read path={tmp_path}/n.txt").tool == "read_file"
