
from aetheris.model import (
    ModelRequest,
    ModelResponse,
    ResponseKind,
)
from aetheris.planner.planner import Planner


class FakeSuggestingProvider:
    """Test provider that suggests a specific tool."""

    name = "test_suggester"

    def __init__(self, tool: str, arg: dict):
        self.tool = tool
        self.arg = arg

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.kind is ResponseKind.PLAN_SUGGESTION:
            return ModelResponse(
                kind=request.kind,
                suggestion={"tool": self.tool, "arg": self.arg},
                provider=self.name,
                ok=True,
            )
        return ModelResponse(kind=request.kind, ok=True, provider=self.name)


def test_planner_uses_model_suggestion_when_not_confident():
    """When deterministic rules don't match, the planner can ask the model."""
    model = FakeSuggestingProvider("read_file", {"path": "/test.txt"})
    planner = Planner(
        model=model,
        registry_tools=("echo", "read_file", "write_file", "list_dir", "shell"),
    )

    # Task that doesn't match any deterministic rule
    plan = planner.plan("summarize the foo.txt file for me")

    # Model suggestion is used
    assert plan.tool == "read_file"
    assert "test.txt" in plan.arg or "/test.txt" in plan.arg
    assert "model suggestion" in plan.reason
    assert not plan.confident


def test_planner_ignores_invalid_model_suggestion():
    """Model suggestion naming a nonexistent tool is discarded."""
    model = FakeSuggestingProvider("nonexistent_tool", {"x": 1})
    planner = Planner(
        model=model,
        registry_tools=("echo", "read_file", "write_file", "list_dir", "shell"),
    )

    plan = planner.plan("do something weird")

    # Model suggestion was discarded; falls back to deterministic echo
    assert plan.tool == "echo"
    assert "fallback" in plan.reason
    assert not plan.confident


def test_planner_still_uses_deterministic_when_confident():
    """When deterministic rules match, model is not even consulted."""
    model = FakeSuggestingProvider("wrong_tool", {"x": 1})
    planner = Planner(
        model=model,
        registry_tools=("echo", "read_file", "write_file", "list_dir", "shell"),
    )

    # Task with explicit shell prefix
    plan = planner.plan("run: echo hello")

    # Deterministic rule is used; model is not consulted
    assert plan.tool == "shell"
    assert plan.confident
    assert "model" not in plan.reason.lower()


def test_planner_without_model_works():
    """Planner without a model still works (backward compatible)."""
    planner = Planner(
        registry_tools=("echo", "read_file", "write_file", "list_dir", "shell"),
    )

    plan = planner.plan("random text with no intent")

    # Falls back to deterministic echo with confidence
    assert plan.tool == "echo"
    assert plan.confident
    assert "default echo" in plan.reason
