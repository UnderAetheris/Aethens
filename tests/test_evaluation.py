from aetheris.evaluation.cases import EvalCase, default_suite
from aetheris.evaluation.evaluator import Evaluator
from aetheris.memory.store import MemoryStore


def _evaluator(tmp_path):
    mem = MemoryStore(str(tmp_path / "eval_log.jsonl"))
    return Evaluator(mem, workspace_root=str(tmp_path)), mem


def test_default_suite_anchors_pass_at_baseline(tmp_path):
    """Anchors must all pass without a model; stretch cases intentionally fail."""
    from aetheris.evaluation.cases import ANCHOR_NAMES

    evaluator, _ = _evaluator(tmp_path)
    report = evaluator.run()
    assert report.total == len(default_suite())

    anchor_results = {r.name: r.passed for r in report.results if r.name in ANCHOR_NAMES}
    assert all(anchor_results.values()), f"anchor failures: {anchor_results}"


def test_results_logged_to_memory(tmp_path):
    evaluator, mem = _evaluator(tmp_path)
    evaluator.run()
    kinds = [e["kind"] for e in mem.history()]
    assert kinds.count("eval_case") == len(default_suite())
    assert "eval_summary" in kinds


def test_summary_records_pass_rate(tmp_path):
    evaluator, mem = _evaluator(tmp_path)
    evaluator.run()
    summary = [e for e in mem.history() if e["kind"] == "eval_summary"][-1]
    # Baseline pass rate is < 1.0 by design (stretch cases need the model).
    assert 0.0 < summary["data"]["pass_rate"] < 1.0
    assert summary["data"]["total"] == len(default_suite())


def test_scorer_detects_wrong_tool(tmp_path):
    evaluator, _ = _evaluator(tmp_path)
    bad = [EvalCase(name="bogus", task="hello there", expected_tool="write_file")]
    report = evaluator.run(bad)
    assert report.passed == 0 and report.pass_rate == 0.0


def test_scorer_detects_wrong_output(tmp_path):
    evaluator, _ = _evaluator(tmp_path)
    bad = [
        EvalCase(
            name="wrong_out", task="hello", expected_tool="echo", expected_output="goodbye"
        )
    ]
    report = evaluator.run(bad)
    assert report.passed == 0


def test_partial_pass_rate(tmp_path):
    evaluator, _ = _evaluator(tmp_path)
    cases = [
        EvalCase(name="good", task="hi", expected_tool="echo"),
        EvalCase(name="bad", task="hi", expected_tool="shell"),
    ]
    report = evaluator.run(cases)
    assert report.passed == 1 and report.total == 2
    assert report.pass_rate == 0.5
