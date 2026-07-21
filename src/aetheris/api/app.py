from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ..config import PromotionConfig
from ..controller.queue import TaskState
from .models import (
    AutonomousCycleOut,
    EvalSummaryOut,
    EventOut,
    ExperienceOut,
    FileFactsOut,
    HealthOut,
    ImprovementOut,
    KnowledgeOut,
    LearnedStepOut,
    LearningStateOut,
    PlanReviewActionIn,
    PlanReviewOut,
    ProjectFactsOut,
    PromotionConfigOut,
    ReflectionEventOut,
    RepairOut,
    RepoModelOut,
    RevertOut,
    ScanReportOut,
    SessionControlOut,
    SessionStatusOut,
    SkillActivityOut,
    SkillDetailOut,
    SkillOut,
    SkillProvenanceOut,
    SymbolOut,
    SymbolRefOut,
    TaskIn,
    TaskOut,
)
from .state import AppState

_ACTIVE = {TaskState.PLANNING, TaskState.EXECUTING}
_SETTLED = {TaskState.DONE, TaskState.BLOCKED, TaskState.FAILED}


def _task_out(rec, plan_source: str = "") -> TaskOut:
    return TaskOut(
        id=rec.id,
        task=rec.task,
        state=rec.state.value,
        detail=rec.detail,
        priority=rec.priority,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        plan_source=plan_source,
    )


def _provenance_for(name: str, memory) -> SkillProvenanceOut | None:
    mined_events = [
        e for e in memory.history()
        if e["kind"] == "skill_candidate_mined"
        and e.get("data", {}).get("name") == name
    ]
    if not mined_events:
        return None
    last = mined_events[-1]
    prov = last["data"].get("provenance", {})
    promoted_events = [
        e for e in memory.history()
        if e["kind"] == "skill_promoted"
        and e.get("data", {}).get("skill_name") == name
    ]
    adopted_verdict = promoted_events[-1]["data"] if promoted_events else None
    return SkillProvenanceOut(
        source_task_ids=prov.get("source_task_ids", []),
        recurrence=prov.get("recurrence", 0),
        shape_tools=prov.get("shape", {}).get("tools", []),
        adopted_verdict=adopted_verdict,
    )


def _symbol_out(sym) -> SymbolOut:
    return SymbolOut(
        name=sym.name,
        kind=sym.kind,
        module=sym.module,
        definition=SymbolRefOut(path=sym.definition.path, line=sym.definition.line),
        exported=sym.exported,
        uses=[SymbolRefOut(path=u.path, line=u.line) for u in sym.uses],
    )


def _file_facts_out(facts) -> FileFactsOut:
    return FileFactsOut(
        path=facts.path,
        module=facts.module,
        is_test=facts.is_test,
        tests_target=facts.tests_target,
        symbols=[_symbol_out(s) for s in facts.symbols],
        imports=list(facts.imports),
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

    app = FastAPI(title="Aetheris Bridge", version="0.2.0", lifespan=lifespan)
    app.state.aetheris = app_state

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:3000",
        ],
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
        plan = s.executive._plan_store.load(task_id)
        plan_source = plan.plan_source if plan else rec.plan_source
        return _task_out(rec, plan_source=plan_source)

    @app.get("/tasks/{task_id}/reflections", response_model=list[ReflectionEventOut])
    def get_task_reflections(task_id: str) -> list[ReflectionEventOut]:
        """Read-only: return all reflection_decision events for a task."""
        if s.queue.get(task_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown task '{task_id}'")
        events = [
            e for e in s.memory.history()
            if e["kind"] == "reflection_decision"
            and e.get("data", {}).get("task_id") == task_id
        ]
        return [
            ReflectionEventOut(
                ts=e.get("ts", 0.0),
                task_id=e["data"]["task_id"],
                step=e["data"]["step"],
                verdict=e["data"]["verdict"],
                reason=e["data"]["reason"],
            )
            for e in events
        ]

    # ------------------------------------------------------------------ #
    # Skill Library Observability endpoints (v0 — read-only)             #
    # ------------------------------------------------------------------ #

    @app.get("/skills", response_model=list[SkillOut])
    def list_skills(include_retired: bool = False) -> list[SkillOut]:
        """List active skills (or all if include_retired=true)."""
        if s.registry is None:
            return []
        skills = s.registry._current().values() if include_retired else s.registry.active_skills()
        result = []
        for skill in skills:
            trigger = skill.trigger_patterns[0] if skill.trigger_patterns else ""
            result.append(SkillOut(
                name=skill.name,
                version=skill.version,
                trigger=trigger,
                params=skill.required_params,
                active=skill.active,
                source="auto_promoted" if skill.id.startswith("auto_") else "hand_authored",
            ))
        result.sort(key=lambda x: (x.name, -x.version))
        return result

    @app.get("/skills/activity", response_model=list[SkillActivityOut])
    def skill_activity(limit: int = 50) -> list[SkillActivityOut]:
        """Recent promotion / rejection / retirement events."""
        kinds = {"skill_promoted", "skill_promotion_rejected", "skill_retired", "skill_demoted"}
        events = [
            e for e in s.memory.history()
            if e["kind"] in kinds
        ][-limit:]
        out = []
        for e in reversed(events):
            data = e.get("data", {})
            kind = e["kind"]
            if kind == "skill_demoted":
                kind = "skill_retired"
            out.append(SkillActivityOut(
                ts=e.get("ts", 0.0),
                kind=kind,
                name=data.get("skill_name", ""),
                version=data.get("version"),
                reason=data.get("reason", ""),
            ))
        return out

    @app.get("/skills/{name}", response_model=SkillDetailOut)
    def get_skill_detail(name: str) -> SkillDetailOut:
        """Get one skill with provenance and version history."""
        if s.registry is None:
            raise HTTPException(status_code=404, detail="skill registry disabled")
        current = s.registry._current()
        match = None
        for skill in current.values():
            if skill.name == name:
                match = skill
                break
        if match is None:
            raise HTTPException(status_code=404, detail=f"unknown skill '{name}'")
        trigger = match.trigger_patterns[0] if match.trigger_patterns else ""
        provenance = _provenance_for(name, s.memory)
        version_history = sorted({
            s.version for s in current.values()
            if s.name == name
        })
        return SkillDetailOut(
            name=match.name,
            version=match.version,
            trigger=trigger,
            params=match.required_params,
            active=match.active,
            source="auto_promoted" if match.id.startswith("auto_") else "hand_authored",
            steps=[{"tool": st.tool, "arg_template": st.arg_template, "depends_on": st.depends_on} for st in match.steps],
            provenance=provenance,
            version_history=version_history,
        )

    @app.get("/config/promotion", response_model=PromotionConfigOut)
    def promotion_config() -> PromotionConfigOut:
        """Current promotion tuning values and their clamped ranges."""
        cfg = s.promotion_config or PromotionConfig.from_env()
        return PromotionConfigOut(
            min_recurrence=cfg.min_recurrence,
            stability_max_repairs=cfg.stability_max_repairs,
            promotion_budget=cfg.promotion_budget,
        )

    # ------------------------------------------------------------------ #
    # Repository Understanding endpoints (v0 — read-only)                #
    # ------------------------------------------------------------------ #

    @app.get("/understanding/model", response_model=RepoModelOut)
    def understanding_model() -> RepoModelOut:
        """Current repository model summary."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        model = s.understanding._model
        return RepoModelOut(
            version=model.version,
            root=model.root,
            language=model.language,
            build_system=model.build_system,
            entrypoints=list(model.entrypoints),
            readme_summary=model.readme_summary,
            architecture_summary=model.architecture_summary,
        )

    @app.get("/understanding/scan", response_model=ScanReportOut)
    def understanding_scan() -> ScanReportOut:
        """Run an incremental scan and return the report."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        report = s.understanding.scan()
        return ScanReportOut(
            changed=report.changed,
            removed=report.removed,
            version=report.version,
            timestamp=report.timestamp,
        )

    @app.get("/understanding/defines/{name}", response_model=list[SymbolOut])
    def understanding_defines(name: str) -> list[SymbolOut]:
        """Symbols defined with this name."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return [_symbol_out(sym) for sym in s.understanding.defines(name)]

    @app.get("/understanding/module_of/{name}")
    def understanding_module_of(name: str) -> dict[str, str | None]:
        """Module where a symbol is defined."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return {"name": name, "module": s.understanding.module_of(name)}

    @app.get("/understanding/exporting_module/{name}")
    def understanding_exporting_module(name: str) -> dict[str, str | None]:
        """Which module exports a symbol (public / __all__)."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return {"name": name, "module": s.understanding.exporting_module(name)}

    @app.get("/understanding/dependents_of/{name}")
    def understanding_dependents(name: str) -> dict[str, list[str]]:
        """Modules that depend on a symbol."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return {"name": name, "dependents": s.understanding.dependents_of(name)}

    @app.get("/understanding/tests_for/{path:path}")
    def understanding_tests_for(path: str) -> dict[str, list[str]]:
        """Test files exercising an implementation path."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return {"path": path, "tests": s.understanding.tests_for(path)}

    @app.get("/understanding/helpers")
    def understanding_helpers(intent: str) -> dict[str, list[SymbolOut]]:
        """Find helper symbols matching an intent (deterministic match)."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return {"intent": intent, "helpers": [_symbol_out(s) for s in s.understanding.find_helper(intent)]}

    @app.get("/understanding/project", response_model=ProjectFactsOut)
    def understanding_project() -> ProjectFactsOut:
        """Project-level facts."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        facts = s.understanding.project_facts()
        return ProjectFactsOut(**facts)

    @app.get("/understanding/files", response_model=list[FileFactsOut])
    def understanding_files() -> list[FileFactsOut]:
        """All indexed files with their facts."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return [_file_facts_out(f) for f in s.understanding._model.files.values()]

    @app.get("/understanding/history")
    def understanding_history() -> list[dict[str, Any]]:
        """Scan journal history."""
        if s.understanding is None:
            raise HTTPException(status_code=404, detail="understanding engine disabled")
        return s.understanding.scan_history()

    # ------------------------------------------------------------------ #
    # Reasoning endpoints (v0 — read-only, advisory)                     #
    # ------------------------------------------------------------------ #

    @app.get("/reasoning/status")
    def reasoning_status() -> dict[str, Any]:
        """Reasoning engine status (read-only).

        Reflects the live configuration: reasoning is now default-on, and an
        env override (AETHERIS_REASONING) is reported when present.  This is a
        window onto state, never a control surface.
        """
        env_override = os.environ.get("AETHERIS_REASONING")
        if s.reasoning is None:
            return {
                "enabled": False,
                "mode": "opt-out",
                "default_on": True,
                "env_override": env_override,
                "history_count": 0,
            }
        return {
            "enabled": True,
            "mode": "default-on",
            "default_on": True,
            "env_override": env_override,
            "budget": {
                "max_depth": s.reasoning._budget.max_depth,
                "max_hypotheses": s.reasoning._budget.max_hypotheses,
                "timeout_ms": s.reasoning._budget.timeout_ms,
                "max_fan_in": s.reasoning._budget.max_fan_in,
                "confidence_floor": s.reasoning._budget.confidence_floor,
            },
            "history_count": len(s.reasoning.reasoning_history()),
        }

    @app.get("/reasoning/history")
    def reasoning_history() -> list[dict[str, Any]]:
        """Deliberation journal (structured records, not chain-of-thought)."""
        if s.reasoning is None:
            raise HTTPException(status_code=404, detail="reasoning engine disabled")
        return s.reasoning.reasoning_history()

    @app.get("/reasoning/deliberate/planning")
    def reasoning_deliberate_planning(task: str) -> dict[str, Any]:
        """Deliberate on a planning decision (advisory)."""
        if s.reasoning is None:
            raise HTTPException(status_code=404, detail="reasoning engine disabled")
        ctx = _PlannerContext(task=task)
        deliberation = s.reasoning.deliberate_for_planning(ctx)
        return _deliberation_to_dict(deliberation)

    @app.get("/reasoning/deliberate/repair")
    def reasoning_deliberate_repair(failure: str) -> dict[str, Any]:
        """Deliberate on a repair decision (advisory)."""
        if s.reasoning is None:
            raise HTTPException(status_code=404, detail="reasoning engine disabled")
        outcome = _ReflectionOutcome(failure=failure)
        deliberation = s.reasoning.deliberate_for_repair(outcome)
        return _deliberation_to_dict(deliberation)

    @app.get("/reasoning/deliberate/promotion")
    def reasoning_deliberate_promotion(candidate: str) -> dict[str, Any]:
        """Deliberate on a promotion decision (advisory)."""
        if s.reasoning is None:
            raise HTTPException(status_code=404, detail="reasoning engine disabled")
        cand = _PromotionCandidate(name=candidate)
        deliberation = s.reasoning.deliberate_for_promotion(cand)
        return _deliberation_to_dict(deliberation)

    # ------------------------------------------------------------------ #
    # Research endpoints (v1 — read-only, advisory, network boundary)    #
    # ------------------------------------------------------------------ #

    @app.get("/research/status")
    def research_status() -> dict:
        """Research engine status (read-only).

        Reflects the live configuration: research is now default-on, and an env
        override (AETHERIS_RESEARCH) is reported when present. This is a window
        onto state, never a control surface -- it cannot fetch, toggle, or
        trigger egress. The only way to change research state is config/env at
        startup. The NetworkPerimeter remains the single egress gate.
        """
        env_override = os.environ.get("AETHERIS_RESEARCH")
        if s.research is None:
            return {
                "enabled": False,
                "mode": "opt-out",
                "default_on": True,
                "env_override": env_override,
            }
        return {
            "enabled": True,
            "mode": "default-on",
            "default_on": True,
            "env_override": env_override,
            "allowlist": list(s.research._perimeter.allowlist()),
        }

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

    @app.post("/learning/improve", response_model=ImprovementOut)
    def trigger_improve() -> ImprovementOut:
        """Run one improvement cycle immediately (eval + learn). Safe to call at any time."""
        s.executive.trigger_improvement()
        result = s.learning.last_result
        if result is None:
            return ImprovementOut(improved=False)
        return ImprovementOut(
            improved=result.accepted,
            accepted_keyword=result.candidate.keyword if result.candidate else None,
            accepted_intent=result.candidate.intent if result.candidate else None,
            baseline_rate=result.baseline_rate,
            new_rate=result.new_rate,
        )

    @app.post("/learning/revert", response_model=RevertOut)
    def revert_last() -> RevertOut:
        """Revert the most recently accepted learning step."""
        removed = s.learning.revert_last()
        if removed is None:
            return RevertOut(reverted=False)
        return RevertOut(reverted=True, intent=removed.intent, keyword=removed.keyword)

    # ------------------------------------------------------------------ #
    # Plan review endpoints                                               #
    # ------------------------------------------------------------------ #

    @app.get("/plan/review", response_model=list[PlanReviewOut])
    def list_pending_plans() -> list[PlanReviewOut]:
        """List all plans awaiting user review."""
        if s.plan_review is None:
            return []
        pending = s.plan_review.pending()
        result = []
        for p in pending:
            result.append(PlanReviewOut(
                review_id=p.review_id,
                task=p.task,
                steps=[{"tool": s.tool, "arg": s.arg, "depends_on": s.depends_on} for s in p.plan.steps],
                source=p.plan.source,
                status=p.status.value,
                created_at=p.created_at,
                user_feedback=p.user_feedback,
            ))
        return result

    @app.get("/plan/review/{review_id}", response_model=PlanReviewOut)
    def get_plan_review(review_id: str) -> PlanReviewOut:
        """Get a specific plan under review."""
        if s.plan_review is None:
            raise HTTPException(status_code=404, detail="plan review disabled")
        pending = s.plan_review.get(review_id)
        if pending is None:
            raise HTTPException(status_code=404, detail=f"unknown review '{review_id}'")
        return PlanReviewOut(
            review_id=pending.review_id,
            task=pending.task,
            steps=[{"tool": s.tool, "arg": s.arg, "depends_on": s.depends_on} for s in pending.plan.steps],
            source=pending.plan.source,
            status=pending.status.value,
            created_at=pending.created_at,
            user_feedback=pending.user_feedback,
        )

    @app.post("/plan/review/{review_id}/approve")
    def approve_plan(review_id: str) -> dict:
        """Approve a plan for execution."""
        if s.plan_review is None:
            raise HTTPException(status_code=404, detail="plan review disabled")
        pending = s.plan_review.approve(review_id)
        if pending is None:
            raise HTTPException(status_code=404, detail=f"unknown review '{review_id}'")
        s.memory.record("plan_review_approved", {"review_id": review_id})
        return {"status": "approved", "review_id": review_id}

    @app.post("/plan/review/{review_id}/reject")
    def reject_plan(review_id: str, body: PlanReviewActionIn) -> dict:
        """Reject a plan with optional feedback."""
        if s.plan_review is None:
            raise HTTPException(status_code=404, detail="plan review disabled")
        pending = s.plan_review.reject(review_id, body.feedback)
        if pending is None:
            raise HTTPException(status_code=404, detail=f"unknown review '{review_id}'")
        s.memory.record("plan_review_rejected", {"review_id": review_id, "feedback": body.feedback})
        return {"status": "rejected", "review_id": review_id, "feedback": body.feedback}

    @app.post("/plan/review/{review_id}/modify")
    def modify_plan(review_id: str, body: PlanReviewActionIn) -> dict:
        """Mark a plan as modified with user feedback."""
        if s.plan_review is None:
            raise HTTPException(status_code=404, detail="plan review disabled")
        # In a full implementation the body would contain the modified plan steps.
        # For now we just record the feedback.
        pending = s.plan_review.get(review_id)
        if pending is None:
            raise HTTPException(status_code=404, detail=f"unknown review '{review_id}'")
        s.memory.record("plan_review_modified", {"review_id": review_id, "feedback": body.feedback})
        return {"status": "modified", "review_id": review_id, "feedback": body.feedback}

    # ------------------------------------------------------------------ #
    # Autonomous loop endpoints                                            #
    # ------------------------------------------------------------------ #

    @app.post("/autonomous/cycle", response_model=AutonomousCycleOut)
    def run_autonomous_cycle() -> AutonomousCycleOut:
        """Run one full autonomous improvement cycle."""
        if s.autonomous is None:
            raise HTTPException(status_code=404, detail="autonomous loop disabled")
        result = s.autonomous.cycle()
        return AutonomousCycleOut(
            learned=result.learned,
            learned_keyword=result.learned_keyword,
            skills_proposed=result.skills_proposed,
            skills_promoted=result.skills_promoted,
            repairs_proposed=result.repairs_proposed,
            repairs_applied=result.repairs_applied,
            discoveries=result.discoveries,
            duration_ms=result.duration_ms,
            errors=result.errors,
            total_cycles=s.autonomous.total_cycles,
            uptime_seconds=s.autonomous.uptime_seconds,
        )

    @app.get("/autonomous/state")
    def autonomous_state() -> dict:
        """Get autonomous loop state."""
        if s.autonomous is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "total_cycles": s.autonomous.total_cycles,
            "uptime_seconds": s.autonomous.uptime_seconds,
            "last_result": {
                "learned": s.autonomous.last_result.learned if s.autonomous.last_result else False,
                "skills_proposed": s.autonomous.last_result.skills_proposed if s.autonomous.last_result else 0,
                "skills_promoted": s.autonomous.last_result.skills_promoted if s.autonomous.last_result else 0,
                "repairs_proposed": s.autonomous.last_result.repairs_proposed if s.autonomous.last_result else 0,
            } if s.autonomous.last_result else None,
        }

    @app.post("/autonomous/repair", response_model=list[RepairOut])
    def trigger_self_repair() -> list[RepairOut]:
        """Detect and apply self-repairs for recurring failures."""
        if s.autonomous is None:
            raise HTTPException(status_code=404, detail="autonomous loop disabled")
        proposals = s.autonomous._detect_recurring_failures()
        results = []
        for proposal in proposals:
            result = s.autonomous._apply_repair(proposal)
            results.append(RepairOut(
                applied=result.applied,
                problem=result.problem,
                reason=result.reason,
            ))
        return results

    # ------------------------------------------------------------------ #
    # Unattended Run Loop & Health Watchdog (v0)                         #
    # Read-only status + conservative lifecycle brakes only.               #
    # ------------------------------------------------------------------ #

    @app.get("/session/status", response_model=SessionStatusOut)
    def session_status(session_id: str | None = None) -> SessionStatusOut:
        """Read-only window onto the supervised session.

        When the supervisor is disabled (unattended off) it returns
        enabled=False and never drives the executive. This endpoint is a window
        plus a brake, never an accelerator.
        """
        if s.unattended is None:
            return SessionStatusOut(enabled=False)
        return SessionStatusOut(**s.unattended.status(session_id))

    @app.post("/session/start", response_model=SessionControlOut)
    def session_start(frontier_ref: str = "default") -> SessionControlOut:
        """Start one bounded, fail-closed supervised session.

        Runs to a terminal/paused state (health check, bounds, or drained
        frontier). Conservative by construction: it may stop, never expand.
        """
        if s.unattended is None:
            raise HTTPException(status_code=404, detail="unattended supervisor disabled")
        session = s.unattended.start(frontier_ref=frontier_ref)
        return SessionControlOut(
            session_id=session.session_id,
            state=session.state.value,
            stop_reason=session.stop_reason,
            steps_taken=session.steps_taken,
        )

    @app.post("/session/resume", response_model=SessionControlOut)
    def session_resume(session_id: str) -> SessionControlOut:
        """Rehydrate from the last confirmed checkpoint and continue."""
        if s.unattended is None:
            raise HTTPException(status_code=404, detail="unattended supervisor disabled")
        session = s.unattended.resume(session_id)
        return SessionControlOut(
            session_id=session.session_id,
            state=session.state.value,
            stop_reason=session.stop_reason,
            steps_taken=session.steps_taken,
        )

    @app.post("/session/pause", response_model=SessionControlOut)
    def session_pause(session_id: str) -> SessionControlOut:
        """Conservative brake: pause a paused/idle session (reduces activity)."""
        if s.unattended is None:
            raise HTTPException(status_code=404, detail="unattended supervisor disabled")
        session = s.unattended.brake(session_id, pause=True)
        return SessionControlOut(
            session_id=session.session_id,
            state=session.state.value,
            stop_reason=session.stop_reason,
            steps_taken=session.steps_taken,
        )

    @app.post("/session/stop", response_model=SessionControlOut)
    def session_stop(session_id: str) -> SessionControlOut:
        """Conservative brake: stop a paused/idle session (reduces activity)."""
        if s.unattended is None:
            raise HTTPException(status_code=404, detail="unattended supervisor disabled")
        session = s.unattended.brake(session_id, pause=False)
        return SessionControlOut(
            session_id=session.session_id,
            state=session.state.value,
            stop_reason=session.stop_reason,
            steps_taken=session.steps_taken,
        )

    return app


# ------------------------------------------------------------------ #
# Reasoning API helper classes (lightweight context carriers)         #
# ------------------------------------------------------------------ #

class _PlannerContext:
    def __init__(self, task: str) -> None:
        self.task = task


class _ReflectionOutcome:
    def __init__(self, failure: str) -> None:
        self.failure = failure
        self.task_id = "api"
        self.step_index = 0
        self.tool = "run_tests"
        self.arg = ""
        self.ok = False
        self.output = failure
        self.blocked = False
        self.attempt = 1


class _PromotionCandidate:
    def __init__(self, name: str) -> None:
        self.name = name
        self.task_id = "api"
        self.benchmark_deltas = {}
        self.history = []


def _deliberation_to_dict(d: Any) -> dict[str, Any]:
    return {
        "seam": d.seam.value,
        "subject": d.subject,
        "assumptions": [{"statement": a.statement, "load_bearing": a.load_bearing} for a in d.assumptions],
        "observations": [{"statement": o.statement, "provenance": {"source": o.provenance.source, "ref": o.provenance.ref}} for o in d.observations],
        "uncertainties": [{"question": u.question, "resolvable_by": u.resolvable_by} for u in d.uncertainties],
        "candidates": [{"approach_id": c.approach_id, "summary": c.summary, "score": c.score} for c in d.candidates],
        "risks": [{"approach_id": r.approach_id, "statement": r.statement, "severity": r.severity} for r in d.risks],
        "consequences": [{"approach_id": c.approach_id, "predicted": c.predicted, "expected_effect": c.expected_effect} for c in d.consequences],
        "confidence": d.confidence,
        "recommendation": d.recommendation.value,
        "recommended_approach": d.recommended_approach,
        "depth_used": d.depth_used,
        "hypotheses_used": d.hypotheses_used,
        "abstained": d.abstained,
        "reason": d.reason,
    }


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("aetheris.api.app:app", host="127.0.0.1", port=8000, reload=True)
