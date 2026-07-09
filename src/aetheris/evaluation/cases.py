from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalCase:
    """One benchmark case.

    - `task` is fed to the controller.
    - `expected_tool` (optional) is checked against the planner's choice.
    - `expected_output` (optional) is checked against the run's output.
    - `fixture` (optional) is (relative_path, content) written into the
      workspace root before the case runs, so file cases are hermetic.
    """

    name: str
    task: str
    expected_tool: str | None = None
    expected_output: str | None = None
    fixture: tuple[str, str] | None = None


def default_suite() -> list[EvalCase]:
    """A small, representative benchmark. Extend by appending cases."""
    return [
        EvalCase(
            name="chat_echoes",
            task="hello aetheris",
            expected_tool="echo",
            expected_output="hello aetheris",
        ),
        EvalCase(
            name="read_returns_content",
            task="read path={root}/note.txt",
            expected_tool="read_file",
            expected_output="benchmark content",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="list_shows_entries",
            task="list path={root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        EvalCase(
            name="write_routes_to_write_file",
            task="create path={root}/out.txt content=data",
            expected_tool="write_file",
        ),
        EvalCase(
            name="ambiguous_falls_back_to_echo",
            task="please save this somewhere",
            expected_tool="echo",
        ),
    ]
