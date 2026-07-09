from aetheris.config import Config
from aetheris.controller.controller import Controller


def test_controller_handles_task(tmp_path):
    controller = Controller(Config(log_path=str(tmp_path / "mem.jsonl")))
    result = controller.handle("ping")
    assert result.ok and result.output == "ping"


def test_memory_records_history(tmp_path):
    controller = Controller(Config(log_path=str(tmp_path / "mem.jsonl")))
    controller.handle("ping")
    kinds = [e["kind"] for e in controller.memory.history()]
    assert "task_received" in kinds and "task_completed" in kinds
