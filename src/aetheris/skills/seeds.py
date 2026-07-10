"""Hand-authored seed skills for Aetheris.

Two seeds, two deliberate purposes:

list_and_read_first  — all-safe, primary validated skill.
    Lists a directory then reads the first file found.
    Encodes the read-after-list dependency once and correctly.
    Runs cleanly in safe_mode; demonstrates reuse + reflection.

create_and_verify    — safety-demonstration skill.
    Writes a file then reads it back to verify.
    write_file is still blocked by the unchanged gate in safe_mode,
    proving a skill gains zero privilege.
    Happy path shown with safe_mode=False.

Triggers are conservative and specific: a vague task that merely
mentions a file must not fire a skill.  Better to miss and plan
normally than fire on a bad fit.
"""
from __future__ import annotations

from .registry import SkillStep, SkillTemplate


def list_and_read_first() -> SkillTemplate:
    """List a directory then read the first file in it.

    Trigger: task must explicitly say 'list and read' or 'lrf' with a dir= param.
    Required params: dir (the directory to list and read from), file (the file to read).

    Conservative trigger: requires both the action phrase AND the dir= param.
    A task like "show me the files" does NOT fire this skill.
    """
    return SkillTemplate(
        id="",
        name="list_and_read_first",
        description=(
            "List a directory then read a named file within it. "
            "Encodes the read-after-list dependency correctly."
        ),
        trigger_patterns=[
            r"\blist\s+and\s+read\b.*\bdir=",
            r"\blrf\b.*\bdir=",
        ],
        required_params=["dir", "file"],
        steps=[
            SkillStep(
                tool="list_dir",
                arg_template='{"path": "{dir}"}',
                reason="list directory",
                depends_on=[],
            ),
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{file}"}',
                reason="read first file",
                depends_on=[0],   # read only after list succeeds
            ),
        ],
    )


def create_and_verify() -> SkillTemplate:
    """Write a file then read it back to verify the write succeeded.

    Trigger: task must say 'create and verify' with path= and content= params.
    Required params: path, content.

    Safety demonstration: write_file is blocked in safe_mode by the unchanged
    SafetyLayer gate.  This skill gains zero privilege — the block fires exactly
    as it would for any other write_file step.
    """
    return SkillTemplate(
        id="",
        name="create_and_verify",
        description=(
            "Write a file then read it back to verify. "
            "Demonstrates that skill steps are gated by SafetyLayer unchanged."
        ),
        trigger_patterns=[
            r"\bcreate\s+and\s+verify\b.*\bpath=",
        ],
        required_params=["path", "content"],
        steps=[
            SkillStep(
                tool="write_file",
                arg_template='{"path": "{path}", "content": "{content}"}',
                reason="write file",
                depends_on=[],
            ),
            SkillStep(
                tool="read_file",
                arg_template='{"path": "{path}"}',
                reason="verify write by reading back",
                depends_on=[0],   # read only after write succeeds
            ),
        ],
    )
