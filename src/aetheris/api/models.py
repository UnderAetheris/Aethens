from __future__ import annotations

from pydantic import BaseModel, Field


class TaskIn(BaseModel):
    task: str = Field(min_length=1, description="The task text to enqueue.")
    priority: int = Field(default=0, description="Higher drains first.")


class TaskOut(BaseModel):
    id: str
    task: str
    state: str
    detail: str = ""
    priority: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    plan_source: str = ""


class EventOut(BaseModel):
    ts: float
    kind: str
    data: dict


class EvalSummaryOut(BaseModel):
    passed: int
    total: int
    pass_rate: float
    ts: float | None = None
    available: bool = True


class KnowledgeOut(BaseModel):
    id: str
    title: str
    source: str
    summary: str
    tags: list[str] = []
    confidence: float = 0.5
    created_at: float = 0.0


class ExperienceOut(BaseModel):
    id: str
    problem: str
    cause: str
    fix: str
    evidence: str = ""
    related_task: str | None = None
    related_eval_case: str | None = None
    confidence: float = 0.5
    created_at: float = 0.0


class LearnedStepOut(BaseModel):
    intent: str
    keyword: str
    from_case: str
    created_at: float


class LearningStateOut(BaseModel):
    extra_keywords: dict[str, list[str]]
    steps: list[LearnedStepOut]


class ImprovementOut(BaseModel):
    improved: bool
    accepted_keyword: str | None = None
    accepted_intent: str | None = None
    baseline_rate: float | None = None
    new_rate: float | None = None


class RevertOut(BaseModel):
    reverted: bool
    intent: str | None = None
    keyword: str | None = None


class ReflectionEventOut(BaseModel):
    ts: float
    task_id: str
    step: int
    verdict: str
    reason: str


class HealthOut(BaseModel):
    status: str = "ok"
    queued: int
    active: int
    settled: int


class PlanReviewOut(BaseModel):
    review_id: str
    task: str
    steps: list[dict]
    source: str
    status: str
    created_at: float
    user_feedback: str = ""


class PlanReviewActionIn(BaseModel):
    feedback: str = ""


class AutonomousCycleOut(BaseModel):
    learned: bool
    learned_keyword: str | None = None
    skills_proposed: int = 0
    skills_promoted: int = 0
    repairs_proposed: int = 0
    repairs_applied: int = 0
    discoveries: int = 0
    duration_ms: float = 0.0
    errors: list[str] = []
    total_cycles: int = 0
    uptime_seconds: float = 0.0


class RepairOut(BaseModel):
    applied: bool
    problem: str
    reason: str


# ---------------------------------------------------------------------------
# Skill Library Observability models (v0 — additive, read-only)
# ---------------------------------------------------------------------------

class SkillProvenanceOut(BaseModel):
    source_task_ids: list[str] = []
    recurrence: int = 0
    shape_tools: list[str] = []
    adopted_verdict: dict | None = None


class SkillOut(BaseModel):
    name: str
    version: int
    trigger: str
    params: list[str]
    usefulness: float = 0.0
    active: bool = True
    source: str = "hand_authored"


class SkillDetailOut(SkillOut):
    steps: list[dict] = []
    provenance: SkillProvenanceOut | None = None
    version_history: list[int] = []


class SkillActivityOut(BaseModel):
    ts: float
    kind: str            # skill_promoted | skill_promotion_rejected | skill_retired
    name: str
    version: int | None = None
    reason: str = ""


class PromotionConfigOut(BaseModel):
    min_recurrence: int
    min_recurrence_range: tuple[int, int] = (2, 20)
    stability_max_repairs: int
    promotion_budget: int
    promotion_budget_range: tuple[int, int] = (1, 5)


# ---------------------------------------------------------------------------
# Repository Understanding models (v0 — additive, read-only)
# ---------------------------------------------------------------------------

class SymbolRefOut(BaseModel):
    path: str
    line: int


class SymbolOut(BaseModel):
    name: str
    kind: str
    module: str
    definition: SymbolRefOut
    exported: bool = False
    uses: list[SymbolRefOut] = []


class FileFactsOut(BaseModel):
    path: str
    module: str
    is_test: bool = False
    tests_target: str | None = None
    symbols: list[SymbolOut] = []
    imports: list[str] = []


class RepoModelOut(BaseModel):
    version: int
    root: str
    language: str = "python"
    build_system: str = ""
    entrypoints: list[str] = []
    readme_summary: str = ""
    architecture_summary: str = ""


class ScanReportOut(BaseModel):
    changed: list[str] = []
    removed: list[str] = []
    version: int = 0
    timestamp: float = 0.0


class ProjectFactsOut(BaseModel):
    language: str = "python"
    build_system: str = ""
    entrypoints: list[str] = []
    readme_summary: str = ""
    architecture_summary: str = ""
    version: int = 0


# ---------------------------------------------------------------------------
# Reasoning models (v0 — read-only, advisory)
# ---------------------------------------------------------------------------

class ReasoningStatusOut(BaseModel):
    enabled: bool = False
    budget: dict | None = None
    history_count: int = 0
