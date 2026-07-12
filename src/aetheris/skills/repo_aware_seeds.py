"""Concrete repo-aware skills + hermetic fixtures for Repo-Aware Coding Skills v0.

Two genuinely repo-aware skills are defined:
  * ``missing_import_skill``  — targets the *correct* exporting module (Understanding
    `exporting_module`), falling back to a best-effort import when unknown.
  * ``helper_reuse_skill``    — reuses an existing helper (`find_helper`) instead of
    reinventing, via a fact-driven candidate shape.

A reasoning-shape-choice skill (``two_shape_skill``) demonstrates the advisory
reasoning path.  Plain twins are the same default shape with facts/reasoning
disabled, used by the benchmark + the canary test.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..planner.plan import MultiStepPlan
from .repo_aware import CandidateShape, FactRequest, RepoAwareSkill, SkillMatcher, SkillStep


# ---------------------------------------------------------------------------
# Skill definitions (data-only)
# ---------------------------------------------------------------------------


def missing_import_skill() -> RepoAwareSkill:
    return RepoAwareSkill(
        name="missing_import_repair",
        version=1,
        match=SkillMatcher(trigger_patterns=["missing import", "import error"], required_params=["symbol", "path"]),
        facts_needed=(
            FactRequest(binding="path", query="param", arg_from="path", default=""),
            FactRequest(binding="symbol", query="param", arg_from="symbol", default=""),
            FactRequest(
                binding="import_module",
                query="exporting_module",
                arg_from="symbol",
                default="<best-effort module>",
            ),
        ),
        consult_reasoning=False,
        candidates=(
            CandidateShape(
                shape_id="plain_import",
                is_default=True,
                steps=(
                    SkillStep(
                        tool="edit_file",
                        arg_template=(
                            '{"path": "{path}", "find": "\\n", '
                            '"replace": "\\nfrom {import_module} import {symbol}\\n"}'
                        ),
                        reason="add import for missing symbol",
                    ),
                ),
            ),
        ),
    )


def helper_reuse_skill() -> RepoAwareSkill:
    return RepoAwareSkill(
        name="helper_reuse_impl",
        version=1,
        match=SkillMatcher(trigger_patterns=["implement", "add helper", "create function"],
                            required_params=["intent", "path"]),
        facts_needed=(
            FactRequest(binding="path", query="param", arg_from="path", default=""),
            FactRequest(binding="helper_name", query="find_helper", arg_from="intent", default=""),
        ),
        consult_reasoning=True,
        candidates=(
            CandidateShape(
                shape_id="fresh_impl",
                is_default=True,
                steps=(
                    SkillStep(
                        tool="edit_file",
                        arg_template=(
                            '{"path": "{path}", "find": "\\n", '
                            '"replace": "\\ndef {helper_name}(data):\\n    return data\\n"}'
                        ),
                        reason="reimplement the helper from scratch",
                    ),
                ),
            ),
            CandidateShape(
                shape_id="reuse_helper",
                requires_binding="helper_name",
                steps=(
                    SkillStep(
                        tool="edit_file",
                        arg_template=(
                            '{"path": "{path}", "find": "\\n", '
                            '"replace": "\\nfrom helpers import {helper_name}\\n"}'
                        ),
                        reason="reuse the existing helper instead of reinventing",
                    ),
                ),
            ),
        ),
    )


def two_shape_skill() -> RepoAwareSkill:
    return RepoAwareSkill(
        name="two_shape_skill",
        version=1,
        match=SkillMatcher(trigger_patterns=["choose shape"], required_params=[]),
        facts_needed=(),
        consult_reasoning=True,
        candidates=(
            CandidateShape(
                shape_id="plain_shape",
                is_default=True,
                steps=(
                    SkillStep(
                        tool="edit_file",
                        arg_template='{"path": "a.py", "find": "\\n", "replace": "\\n# plain\\n"}',
                        reason="plain default shape",
                    ),
                ),
            ),
            CandidateShape(
                shape_id="safe_shape",
                steps=(
                    SkillStep(
                        tool="edit_file",
                        arg_template='{"path": "a.py", "find": "\\n", "replace": "\\n# safe\\n"}',
                        reason="reasoning-advised safer shape",
                    ),
                ),
            ),
        ),
    )


def plain_twin(skill: RepoAwareSkill) -> RepoAwareSkill:
    """The plain twin: same default shape, facts + reasoning disabled.

    Used by the benchmark (off = understanding None) and the canary test
    (repo-aware with reasoning off must equal this twin's behavior).
    """
    return RepoAwareSkill(
        name=f"{skill.name}_plain",
        version=skill.version,
        match=skill.match,
        facts_needed=(),
        consult_reasoning=False,
        candidates=(skill.default_shape(),),
    )


# ---------------------------------------------------------------------------
# Hermetic fixtures + tasks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillFixture:
    name: str
    task: str
    fixtures: dict[str, str]
    verify: Callable[[MultiStepPlan], bool] = lambda plan: True  # ground-truth correctness


def correct_module_fixture() -> SkillFixture:
    return SkillFixture(
        name="correct_module_import",
        task="fix missing import symbol=parse_config path=src/pkg/main.py",
        fixtures={
            "src/pkg/__init__.py": "",
            "src/pkg/config.py": "def parse_config(data):\n    return data\n",
            "src/pkg/main.py": "def run():\n    return parse_config(1)\n",
        },
    )


def helper_reuse_fixture() -> SkillFixture:
    return SkillFixture(
        name="helper_reuse",
        task="implement helper intent=parse_config path=src/pkg/main.py",
        fixtures={
            "src/pkg/__init__.py": "",
            "src/pkg/helpers.py": "def parse_config(data):\n    return data\n",
            "src/pkg/main.py": "def run():\n    return 1\n",
        },
    )


def correct_module_ground_truth_module() -> str:
    return "src.pkg.config"
