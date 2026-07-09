from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..controller.queue import TaskState
from .models import (
    EvalSummaryOut,
    EventOut,
    ExperienceOut,
    HealthOut,
    KnowledgeOut,
    LearnedStepOut,
    LearningStateOut,
    TaskIn,
    TaskOut,
)
from .state import AppState

_ACTIVE = {TaskState.PLANNING, TaskState.EXECUTING}
_SETTLED = {TaskState.DONE, TaskState.BLOCKED, TaskState.FAILED}


def _task_out(rec) -> TaskOut:
    return TaskOut(
        id=rec.id,
        task=rec.task,
        state=rec.state.value,
        detail=rec.detail,
        priority=rec.priority,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def create_app(state: AppState | None = None, auto_tick: bool = True, tick_interval: float = 1.0) -> FastAPI:
    app_state = state or AppState.create()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = None
        if auto_tick:
            async def drain_loop() -> None:
                while True:
                    app_state.executive.run_once()
                    await asyncio.sleep(tick_interval)

            task = asyncio.create_task(drain_loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Aetheris Bridge", version="0.1.0", lifespan=lifespan)
    app.state.aetheris = app_state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    s = app_state

    @app.get("/health", response_model=HealthOut)
    def health() -> HealthOut:
        tasks = s.queue.all()
        return HealthOut(
            queued=sum(1 for t in tasks if t.state == TaskState.QUEUED),
            active=sum(1 for t in tasks if t.state in _ACTIVE),
            settled=sum(1 for t in tasks if t.state in _SETTLED),
        )

    @app.post("/tasks", response_model=TaskOut, status_code=201)
    def submit_task(body: TaskIn) -> TaskOut:
        rec = s.queue.enqueue(body.task, priority=body.priority)
        return _task_out(rec)

    @app.get("/tasks", response_model=list[TaskOut])
    def list_tasks(state_filter: str | None = None) -> list[TaskOut]:
        tasks = s.queue.all()
        if state_filter:
            tasks = [t for t in tasks if t.state.value == state_filter]
        tasks.sort(key=lambda t: t.updated_at, reverse=True)
        return [_task_out(t) for t in tasks]

    @app.get("/tasks/{task_id}", response_model=TaskOut)
    def get_task(task_id: str) -> TaskOut:
        rec = s.queue.get(task_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"unknown task '{task_id}'")
        return _task_out(rec)

    @app.get("/events/recent", response_model=list[EventOut])
    def recent_events(limit: int = 50) -> list[EventOut]:
        history = s.memory.history()[-limit:]
        return [
            EventOut(ts=e.get("ts", 0.0), kind=e["kind"], data=e.get("data", {}))
            for e in reversed(history)
        ]

    @app.get("/evaluation/summary", response_model=EvalSummaryOut)
    def eval_summary() -> EvalSummaryOut:
        summaries = [e for e in s.memory.history() if e["kind"] == "eval_summary"]
        if not summaries:
            return EvalSummaryOut(passed=0, total=0, pass_rate=0.0, available=False)
        d = summaries[-1]["data"]
        return EvalSummaryOut(
            passed=d.get("passed", 0),
            total=d.get("total", 0),
            pass_rate=d.get("pass_rate", 0.0),
            ts=d.get("ts"),
        )

    @app.get("/memory/knowledge", response_model=list[KnowledgeOut])
    def knowledge() -> list[KnowledgeOut]:
        return [KnowledgeOut(**k.to_dict()) for k in s.knowledge.all()]

    @app.get("/memory/experience", response_model=list[ExperienceOut])
    def experience() -> list[ExperienceOut]:
        return [ExperienceOut(**e.to_dict()) for e in s.experience.all()]

    @app.get("/learning/state", response_model=LearningStateOut)
    def learning_state() -> LearningStateOut:
        return LearningStateOut(
            extra_keywords=s.learned.as_keywords(),
            steps=[LearnedStepOut(**st.to_dict()) for st in s.learned.steps()],
        )

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("aetheris.api.app:app", host="127.0.0.1", port=8000, reload=True)
