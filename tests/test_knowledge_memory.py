from aetheris.memory.experience import ExperienceStore
from aetheris.memory.knowledge import KnowledgeStore


def test_knowledge_append_and_read_back(tmp_path):
    ks = KnowledgeStore(str(tmp_path / "know.jsonl"))
    entry = ks.add(
        title="Safety gate",
        source="doc:safety-v0",
        summary="All tool calls route through SafetyLayer.run().",
        tags=["safety", "architecture"],
        confidence=0.9,
    )
    assert entry.id.startswith("know-0001-")
    back = ks.get(entry.id)
    assert back is not None and back.title == "Safety gate"
    assert back.tags == ["safety", "architecture"]


def test_knowledge_ids_are_unique_and_ordered(tmp_path):
    ks = KnowledgeStore(str(tmp_path / "know.jsonl"))
    a = ks.add("A", "s", "first")
    b = ks.add("B", "s", "second")
    assert a.id != b.id
    assert a.id.startswith("know-0001-") and b.id.startswith("know-0002-")


def test_knowledge_search_by_query_and_tag(tmp_path):
    ks = KnowledgeStore(str(tmp_path / "know.jsonl"))
    ks.add("Planner rules", "doc:planner", "First match wins.", tags=["planner"])
    ks.add("Shell allowlist", "doc:tools", "Only allowlisted commands.", tags=["safety"])
    assert len(ks.search(query="match")) == 1
    assert len(ks.search(tag="safety")) == 1
    assert len(ks.search()) == 2


def test_experience_append_and_read_back(tmp_path):
    es = ExperienceStore(str(tmp_path / "exp.jsonl"))
    entry = es.add(
        problem="Shell test failed on Windows",
        cause="shlex.split + no shell=True",
        fix="Use shell=True on Windows, keep allowlist",
        evidence="pytest -q output",
        related_task="task:tool-system-v0",
        related_eval_case="shell_allowed",
        confidence=0.8,
    )
    assert entry.id.startswith("exp-0001-")
    back = es.get(entry.id)
    assert back is not None and back.cause.startswith("shlex")


def test_experience_link_to_task_and_eval_case(tmp_path):
    es = ExperienceStore(str(tmp_path / "exp.jsonl"))
    es.add("p1", "c1", "f1", related_task="task:abc", related_eval_case="case_x")
    es.add("p2", "c2", "f2", related_task="task:xyz", related_eval_case="case_x")
    assert len(es.for_task("task:abc")) == 1
    assert len(es.for_eval_case("case_x")) == 2


def test_experience_search_by_query(tmp_path):
    es = ExperienceStore(str(tmp_path / "exp.jsonl"))
    es.add("Path traversal", "unresolved path", "resolve + check root")
    es.add("Timeout", "slow command", "add 10s timeout")
    assert len(es.search(query="traversal")) == 1
    assert len(es.search(query="timeout")) == 1


def test_stores_are_independent(tmp_path):
    ks = KnowledgeStore(str(tmp_path / "know.jsonl"))
    es = ExperienceStore(str(tmp_path / "exp.jsonl"))
    ks.add("K", "s", "knowledge")
    es.add("p", "c", "f")
    assert len(ks.all()) == 1 and len(es.all()) == 1
