import tempfile
from pathlib import Path
from aetheris.skills.repo_aware import RepoAwareSkillRenderer
from aetheris.skills.repo_aware import _understanding_from_fixtures
from aetheris.skills.repo_aware_seeds import (
    missing_import_skill, helper_reuse_skill, two_shape_skill, plain_twin,
    correct_module_fixture, helper_reuse_fixture,
)
from aetheris.skills.repo_aware_benchmark import skill_benchmark, RepoAwareComparison

# missing-import correct module
fx = correct_module_fixture()
root = Path(tempfile.mkdtemp())
u = _understanding_from_fixtures(root, fx.fixtures)
r = RepoAwareSkillRenderer(understanding=u)
plan = r.render(missing_import_skill(), fx.task)
print("MISSING-IMPORT on:", [(s.tool, s.arg) for s in plan.steps])
print("  plan_source:", plan.plan_source, "valid_dag:", plan.is_valid_dag())
print("  journal:", r.render_history()[-1]["facts_used"])

# helper reuse
hf = helper_reuse_fixture()
root2 = Path(tempfile.mkdtemp())
u2 = _understanding_from_fixtures(root2, hf.fixtures)
r2 = RepoAwareSkillRenderer(understanding=u2)
p2 = r2.render(helper_reuse_skill(), hf.task)
print("HELPER-REUSE on:", [(s.tool, s.arg) for s in p2.steps], "shape:", p2.plan_source.split(":")[-1])

# missing fact fallback
r3 = RepoAwareSkillRenderer(understanding=u)
p3 = r3.render(missing_import_skill(), "fix missing import symbol=unknown_sym path=src/pkg/main.py")
print("MISSING-FACT fallback:", [(s.tool, s.arg) for s in p3.steps])

# two-shape with reasoning=None (canary path)
r4 = RepoAwareSkillRenderer(understanding=None, reasoning=None)
p4 = r4.render(two_shape_skill(), "choose shape")
pt = RepoAwareSkillRenderer(understanding=None, reasoning=None).render(plain_twin(two_shape_skill()), "choose shape")
print("TWO-SHAPE off shape:", p4.plan_source.split(":")[-1], "plain twin shape:", pt.plan_source.split(":")[-1])
print("  equal sig:", [s.arg for s in p4.steps] == [s.arg for s in pt.steps])

# comparison suite
print("\n--- comparison ---")
for fx_i, skill in skill_benchmark():
    res = RepoAwareComparison().run(fx_i, skill)
    print(f"{res.skill:24s} promote={res.promote} on={res.on} off={res.off} {res.gate}")
