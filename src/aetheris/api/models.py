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


class HealthOut(BaseModel):
    status: str = "ok"
    queued: int
    active: int
    settled: int
