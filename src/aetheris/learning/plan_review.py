"""Plan review: present plans to the user for verification before execution.

The user said: "if the ai doesnt know that then it go to learn that and
create a skill itself before that make a plan for that and show it to me,
so we can verifiy."

This module provides:
- PlanReviewQueue: stores pending plans awaiting user approval
- ReviewStatus: enum for plan states (pending, approved, rejected, modified)
- Integration with ExecutiveController: only execute approved plans
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

from ..planner.plan import MultiStepPlan


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"


@dataclass
class PendingPlan:
    """A plan waiting for user review."""
    review_id: str
    task: str
    plan: MultiStepPlan
    status: ReviewStatus = ReviewStatus.PENDING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    user_feedback: str = ""
    modified_plan: MultiStepPlan | None = None


class PlanReviewQueue:
    """In-memory queue of plans awaiting user review.

    In production this would be persisted (Redis, DB, or JSONL).
    For now it lives in memory and is wired to the API layer.
    """

    def __init__(self) -> None:
        self._queue: dict[str, PendingPlan] = {}

    def submit(self, task: str, plan: MultiStepPlan) -> PendingPlan:
        """Submit a plan for review. Returns the pending plan."""
        review_id = str(uuid.uuid4())[:8]
        pending = PendingPlan(
            review_id=review_id,
            task=task,
            plan=plan,
            status=ReviewStatus.PENDING,
        )
        self._queue[review_id] = pending
        return pending

    def get(self, review_id: str) -> PendingPlan | None:
        return self._queue.get(review_id)

    def pending(self) -> list[PendingPlan]:
        return [p for p in self._queue.values() if p.status == ReviewStatus.PENDING]

    def all(self) -> list[PendingPlan]:
        return list(self._queue.values())

    def approve(self, review_id: str) -> PendingPlan | None:
        pending = self._queue.get(review_id)
        if pending is None:
            return None
        pending.status = ReviewStatus.APPROVED
        pending.updated_at = time.time()
        return pending

    def reject(self, review_id: str, feedback: str = "") -> PendingPlan | None:
        pending = self._queue.get(review_id)
        if pending is None:
            return None
        pending.status = ReviewStatus.REJECTED
        pending.user_feedback = feedback
        pending.updated_at = time.time()
        return pending

    def modify(self, review_id: str, modified_plan: MultiStepPlan, feedback: str = "") -> PendingPlan | None:
        pending = self._queue.get(review_id)
        if pending is None:
            return None
        pending.status = ReviewStatus.MODIFIED
        pending.modified_plan = modified_plan
        pending.user_feedback = feedback
        pending.updated_at = time.time()
        return pending
