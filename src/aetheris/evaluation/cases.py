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


# ---------------------------------------------------------------------------
# Anchor names — used by tests to assert these never regress.
# ---------------------------------------------------------------------------
ANCHOR_NAMES: frozenset[str] = frozenset({
    "anchor_chat_echoes",
    "anchor_read_returns_content",
    "anchor_list_shows_entries",
    "anchor_write_routes_to_write_file",
    "anchor_shell_explicit_prefix",
})

# Ambiguity-guard names — must always resolve to echo, model must not override.
AMBIGUITY_GUARD_NAMES: frozenset[str] = frozenset({
    "guard_vague_save",
    "guard_vague_do_something",
})


def default_suite() -> list[EvalCase]:
    """20-case benchmark: 5 anchors + 13 stretch + 2 ambiguity guards.

    Anchors (5): trivially deterministic; must pass at baseline and stay
    passing with the model — regression tripwires.

    Stretch (13): realistic non-trigger phrasings (pull up, inspect, dump …)
    that the deterministic rules miss and fall to low-confidence echo.
    These are the exact cases where the model is consulted.  Only
    expected_tool is asserted; output is environment-dependent.

    Ambiguity guards (2): genuinely vague tasks that must stay echo even
    when a model is present — the model must abstain, not over-reach.
    """
    return [
        # ── Anchors ──────────────────────────────────────────────────────────
        EvalCase(
            name="anchor_chat_echoes",
            task="hello aetheris",
            expected_tool="echo",
            expected_output="hello aetheris",
        ),
        EvalCase(
            name="anchor_read_returns_content",
            task="read path={root}/note.txt",
            expected_tool="read_file",
            expected_output="benchmark content",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="anchor_list_shows_entries",
            task="list path={root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        EvalCase(
            name="anchor_write_routes_to_write_file",
            task="create path={root}/out.txt content=data",
            expected_tool="write_file",
        ),
        EvalCase(
            name="anchor_shell_explicit_prefix",
            task="run: echo hello",
            expected_tool="shell",
        ),
        # ── Stretch: read phrasings ───────────────────────────────────────────
        EvalCase(
            name="stretch_pull_up_file",
            task="pull up {root}/note.txt",
            expected_tool="read_file",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="stretch_inspect_file",
            task="inspect {root}/note.txt",
            expected_tool="read_file",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="stretch_whats_inside_file",
            task="what's inside {root}/note.txt",
            expected_tool="read_file",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="stretch_dump_file",
            task="dump {root}/note.txt",
            expected_tool="read_file",
            fixture=("note.txt", "benchmark content"),
        ),
        EvalCase(
            name="stretch_fetch_file",
            task="fetch the contents of {root}/note.txt",
            expected_tool="read_file",
            fixture=("note.txt", "benchmark content"),
        ),
        # ── Stretch: list phrasings ───────────────────────────────────────────
        EvalCase(
            name="stretch_browse_directory",
            task="browse {root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        EvalCase(
            name="stretch_enumerate_directory",
            task="enumerate files in {root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        EvalCase(
            name="stretch_whats_in_directory",
            task="what's in {root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        EvalCase(
            name="stretch_show_directory_contents",
            task="show me what's in {root}",
            expected_tool="list_dir",
            fixture=("a.txt", ""),
        ),
        # ── Stretch: write phrasings ──────────────────────────────────────────
        EvalCase(
            name="stretch_put_content_in_file",
            task="put hello world into {root}/out.txt",
            expected_tool="write_file",
        ),
        EvalCase(
            name="stretch_store_text_in_file",
            task="store the text hello in {root}/out.txt",
            expected_tool="write_file",
        ),
        EvalCase(
            name="stretch_persist_to_file",
            task="persist hello to {root}/out.txt",
            expected_tool="write_file",
        ),
        EvalCase(
            name="stretch_jot_down_to_file",
            task="jot down hello in {root}/out.txt",
            expected_tool="write_file",
        ),
        # ── Ambiguity guards ──────────────────────────────────────────────────
        EvalCase(
            name="guard_vague_save",
            task="please save this somewhere",
            expected_tool="echo",
        ),
        EvalCase(
            name="guard_vague_do_something",
            task="do something useful",
            expected_tool="echo",
        ),
    ]
