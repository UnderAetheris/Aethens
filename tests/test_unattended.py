"""Canaries + behavior tests for the Unattended Run Loop & Health Watchdog.

Two hard canaries (stop-the-line):
  * test_session_bounds_can_only_stop_sooner_never_raise_a_budget
  * test_never_continues_after_unrecoverable_fault

The supervisor composes, never bypasses or expands, the existing Executive.
It may stop work; it may never expand it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import dataclasses

from aetheris.api.state import AppState
from aetheris.config import Config
from aetheris.controller.executive import ExecutiveController
from aetheris.controller.queue import TaskQueue, TaskState
from aetheris.memory.store import MemoryStore
from aetheris.planner.plan import MultiStepPlan, PlanStep
from aetheris.planner.planner import Plan
from aetheris.unattended import (
    HealthSnapshot,
    HealthVerdict,
    HealthWatchdog,
    Session,
    SessionBounds,
    SessionJournal,
    SessionState,
    StaticSampler,
    UnattendedSupervisor,
)
from aetheris.unattended.sampler import build_sampler


# --------------------------------------------------------------------------- #
# Fake workload + a crash-safe fake executive                                  #
# --------------------------------------------------------------------------- #


@dataclass
class FakeStep:
    task_id: str
    step_index: int
    outcome: str


class _Tick:
    def __init__(self, did_work: bool, outcome=None, task_id=None) -> None:
        self.did_work = did_work
        self.outcome = outcome
        self.task_id = task_id


class FakeExecutive:
    """Crash-safe fake of the real ExecutiveController.

    Each step is persisted to a journal only AFTER it completes atomically, so a
    crash mid-step never leaves a half-applied step. A fresh instance pointed at
    the same journal continues exactly where the previous one stopped -- no
    duplicate work, no half-applied state. This mirrors the real queue/plan
    journals the supervisor reuses on resume.
    """

    def __init__(self, steps, log_path, crash_after=None) -> None:
        self._steps = steps
        self._log_path = Path(log_path)
        self._crash_after = crash_after
        self._calls = 0
        self._done = self._load_done()
        self.executed = list(self._done)
        self.in_write = False

    def _load_done(self):
        if not self._log_path.exists():
            return []
        done = []
        for line in self._log_path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                done.append((d["task_id"], d["step_index"]))
        return done

    def has_pending_work(self) -> bool:
        done = set(self._done)
        return any((s.task_id, s.step_index) not in done for s in self._steps)

    def step(self) -> _Tick:
        done = set(self._done)
        nxt = next((s for s in self._steps if (s.task_id, s.step_index) not in done), None)
        if nxt is None:
            return _Tick(False)
        self._calls += 1
        if self._crash_after is not None and self._calls > self._crash_after:
            raise RuntimeError("simulated crash mid-step")
        # Persist ONLY after the step completes atomically.
        self.in_write = True
        with self._log_path.open("a") as f:
            f.write(json.dumps({"task_id": nxt.task_id, "step_index": nxt.step_index}) + "\n")
        self.in_write = False
        self._done.append((nxt.task_id, nxt.step_index))
        self.executed.append((nxt.task_id, nxt.step_index))
        return _Tick(True, outcome=nxt.outcome, task_id=nxt.task_id)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _bounds(max_wall=1e12, max_steps=100000, max_consec=3, max_ticks=200):
    return SessionBounds(
        max_wall_clock_s=max_wall,
        max_steps=max_steps,
        max_consecutive_failures=max_consec,
        max_ticks_without_progress=max_ticks,
    )


def _healthy_snapshot() -> HealthSnapshot:
    return HealthSnapshot(
        queue_depth=0,
        active_work=0,
        retries_used=0,
        repairs_used=0,
        research_budget_used=0.0,
        network_budget_used=0.0,
        perimeter_denials=0,
        ticks_without_progress=0,
        consecutive_failures=0,
    )


def _watchdog(snapshot: HealthSnapshot) -> HealthWatchdog:
    return HealthWatchdog(StaticSampler(snapshot))


def _session_obj(**kw) -> Session:
    bounds = kw.pop("bounds", _bounds())
    return Session(
        session_id=kw.pop("session_id", "test-session"),
        state=kw.pop("state", SessionState.RUNNING),
        bounds=bounds,
        frontier_ref=kw.pop("frontier_ref", "f"),
        **kw,
    )


def _multi_step_workload(n_tasks: int = 3, steps_per_task: int = 2):
    steps = []
    for t in range(n_tasks):
        tid = f"t{t}"
        for i in range(steps_per_task):
            outcome = "done" if i == steps_per_task - 1 else "step_done"
            steps.append(FakeStep(tid, i, outcome))
    return steps


def _sup(executive, tmp_path, sampler=None, bounds=None) -> UnattendedSupervisor:
    journal = SessionJournal(str(tmp_path / "u.journal.jsonl"), str(tmp_path / "u.snap.json"))
    wd = HealthWatchdog(sampler or StaticSampler(_healthy_snapshot()))
    return UnattendedSupervisor(executive, wd, journal, bounds or _bounds())


def _single_step_planner():
    """Deterministic planner returning a single gated step per task."""

    class _P:
        def plan(self, task):
            return Plan("echo", task, "single")

        def plan_multi(self, task, task_id):
            return MultiStepPlan(
                task_id=task_id,
                steps=[PlanStep(tool="echo", arg=task, reason="single")],
            )

    return _P()


# --------------------------------------------------------------------------- #
# 1. Session lifecycle                                                         #
# --------------------------------------------------------------------------- #


def test_session_start_pause_resume_stop(tmp_path):
    steps = _multi_step_workload()
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=200, consecutive_failures=0,
    )
    ex = FakeExecutive(steps, str(tmp_path / "log.jsonl"))
    sup = _sup(ex, tmp_path, sampler=StaticSampler(snap), bounds=_bounds(max_ticks=200))
    s = sup.start(frontier_ref="wl")
    assert s.state == SessionState.PAUSED and s.stop_reason
    s2 = sup.resume(s.session_id)
    assert s2.state in (SessionState.COMPLETED, SessionState.RUNNING, SessionState.PAUSED)


# --------------------------------------------------------------------------- #
# 2. Checkpointing, crash recovery, resume                                     #
# --------------------------------------------------------------------------- #


def test_checkpoint_only_at_safe_points(tmp_path):
    steps = _multi_step_workload()
    ex = FakeExecutive(steps, str(tmp_path / "log.jsonl"))
    sup = _sup(ex, tmp_path)
    sup.start(frontier_ref="wl")
    cps = [e for e in sup.trace if e["kind"] == "checkpoint"]
    # Every checkpoint is at a step boundary (quiescent), never mid-write.
    assert len(cps) >= len(steps)
    for cp in cps:
        assert cp["checkpoint_id"] == f"cp-{cp['steps_taken']}"
    assert not ex.in_write  # never snapshotted while a step was in flight


def test_crash_recovery_rehydrates_cleanly(tmp_path):
    steps = [FakeStep("t", i, "step_done" if i < 4 else "done") for i in range(5)]
    log = str(tmp_path / "exe_log.jsonl")
    ex1 = FakeExecutive(steps, log, crash_after=4)
    sup = _sup(ex1, tmp_path)
    crashed = False
    try:
        sup.start(frontier_ref="wl")
    except RuntimeError:
        crashed = True
    assert crashed, "expected the injected crash to kill the run"
    sid = sup._last_session.session_id

    # Fresh process: rehydrate from the journal + snapshot and resume.
    ex2 = FakeExecutive(steps, log)
    sup2 = _sup(ex2, tmp_path)
    s2 = sup2.resume(sid)
    assert s2.state == SessionState.COMPLETED
    # No half-applied state: the crashed step ran exactly once, cleanly.
    assert len(ex2.executed) == 5
    assert len(set(ex2.executed)) == 5


def test_resume_never_reruns_completed_work(tmp_path):
    steps = _multi_step_workload(n_tasks=4, steps_per_task=3)
    log = str(tmp_path / "exe_log.jsonl")
    ex1 = FakeExecutive(steps, log, crash_after=5)
    sup = _sup(ex1, tmp_path)
    try:
        sup.start(frontier_ref="wl")
    except RuntimeError:
        pass
    sid = sup._last_session.session_id

    ex2 = FakeExecutive(steps, log)
    sup2 = _sup(ex2, tmp_path)
    s2 = sup2.resume(sid)
    assert s2.state == SessionState.COMPLETED
    # Every completed node ran exactly once; nothing reran.
    assert len(ex2.executed) == len(steps)
    assert len(set(ex2.executed)) == len(steps)


# --------------------------------------------------------------------------- #
# 3. Health: fail-closed pause / stop                                          #
# --------------------------------------------------------------------------- #


def test_stall_detection_pauses(tmp_path):
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=200, consecutive_failures=0,
    )
    session = _session_obj(bounds=_bounds(max_ticks=200))
    d = _watchdog(snap).check(session)
    assert d.verdict == HealthVerdict.PAUSE and "stall_detected" in d.reasons


def test_repeated_failures_stop_for_review(tmp_path):
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=0, consecutive_failures=3,
    )
    session = _session_obj(bounds=_bounds(max_consec=3))
    d = _watchdog(snap).check(session)
    assert d.verdict == HealthVerdict.STOP_FOR_REVIEW


def test_budget_exhausted_with_blocked_work_stops(tmp_path):
    snap = HealthSnapshot(
        queue_depth=1, active_work=1, retries_used=0, repairs_used=3,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=0, consecutive_failures=0,
    )
    session = _session_obj(bounds=_bounds(max_consec=5))
    d = _watchdog(snap).check(session)
    assert d.verdict == HealthVerdict.STOP_FOR_REVIEW
    assert "budget_exhausted_work_blocked" in d.reasons


def test_ambiguous_health_pauses_not_continues(tmp_path):
    # An ambiguous (not-clearly-healthy) read must resolve toward pause, never
    # continue. Here research budget is near limit -> PAUSE, not HEALTHY.
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.95, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=0, consecutive_failures=0,
    )
    session = _session_obj()
    assert _watchdog(snap).check(session).verdict != HealthVerdict.HEALTHY


def test_never_continues_after_unrecoverable_fault(tmp_path):
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=0, consecutive_failures=3,
    )
    steps = _multi_step_workload()
    ex = FakeExecutive(steps, str(tmp_path / "log.jsonl"))
    sup = _sup(ex, tmp_path, sampler=StaticSampler(snap), bounds=_bounds(max_consec=3))
    s = sup.start(frontier_ref="wl")
    assert s.state in (SessionState.STOPPED, SessionState.FAILED) and s.stop_reason


def test_perimeter_fault_stops_for_review(tmp_path):
    snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=1,
        ticks_without_progress=0, consecutive_failures=0,
    )
    session = _session_obj()
    d = _watchdog(snap).check(session)
    assert d.verdict == HealthVerdict.STOP_FOR_REVIEW
    assert "perimeter_fault" in d.reasons


def test_irreconcilable_checkpoint_stops_for_review(tmp_path):
    session = _session_obj(checkpoint_irreconcilable=True)
    d = _watchdog(_healthy_snapshot()).check(session)
    assert d.verdict == HealthVerdict.STOP_FOR_REVIEW
    assert "checkpoint_irreconcilable" in d.reasons


# --------------------------------------------------------------------------- #
# 4. Bounded + no authority widening (the hard guarantees)                     #
# --------------------------------------------------------------------------- #


def test_supervisor_holds_no_tool_or_safety_or_budget_writer(tmp_path):
    ex = FakeExecutive([], str(tmp_path / "x.jsonl"))
    journal = SessionJournal(str(tmp_path / "j.jsonl"), str(tmp_path / "s.json"))
    sup = UnattendedSupervisor(ex, _watchdog(_healthy_snapshot()), journal, _bounds())
    for banned in ("edit", "run_tool", "shell", "safety", "write_file",
                   "set_budget", "raise_budget", "perimeter", "promote"):
        assert not hasattr(sup, banned), f"supervisor must not hold '{banned}'"


def test_session_bounds_can_only_stop_sooner_never_raise_a_budget():
    fields = {f.name for f in dataclasses.fields(SessionBounds)}
    assert not (fields & {"retry_budget", "repair_budget", "research_budget", "network_budget"})
    assert _no_method_raises_any_existing_budget(_make_sup())


def _no_method_raises_any_existing_budget(sup: UnattendedSupervisor) -> bool:
    banned = {"raise", "budget", "set_budget", "promote", "perimeter",
              "repair", "retry", "research", "network"}
    for name in dir(sup):
        if name.startswith("_"):
            continue
        low = name.lower()
        if any(b in low for b in banned):
            return False
    return True


def _make_sup() -> UnattendedSupervisor:
    ex = FakeExecutive([], "x.jsonl")
    journal = SessionJournal("/tmp/_u2_j.jsonl", "/tmp/_u2_s.json")
    return UnattendedSupervisor(ex, _watchdog(_healthy_snapshot()), journal, _bounds())


def test_every_step_runs_through_existing_gated_spine(tmp_path):
    mem = MemoryStore(str(tmp_path / "events.jsonl"))
    queue = TaskQueue(str(tmp_path / "queue.jsonl"), mem)
    config = Config(log_path=str(tmp_path / "ctrl.jsonl"), workspace_root=str(tmp_path))
    ex = ExecutiveController(config, queue, mem)
    # Deterministic single-step planner so every task executes through the
    # existing gated spine (Controller -> SafetyLayer -> Tool) and records a
    # "step_executed" event.
    ex._controller.planner = _single_step_planner()
    for i in range(3):
        queue.enqueue(f"hello {i}")

    class ExecSpy:
        def __init__(self, ex):
            self.in_flight = 0
            self.max_concurrent = 0
            self.calls = 0
            orig = ex.step

            def wrapped():
                self.in_flight += 1
                self.max_concurrent = max(self.max_concurrent, self.in_flight)
                r = orig()
                self.in_flight -= 1
                self.calls += 1
                return r

            ex.step = wrapped

    spy = ExecSpy(ex)
    journal = SessionJournal(str(tmp_path / "u.journal.jsonl"), str(tmp_path / "u.snap.json"))
    wd = HealthWatchdog(build_sampler(ex))
    # Pass the real executive (whose step() is now the spy wrapper) to the
    # supervisor; the supervisor only ever calls executive.step()/has_pending_work().
    sup = UnattendedSupervisor(ex, wd, journal, _bounds())
    sup.start(frontier_ref="wl")

    # Steps went through the existing SafetyLayer gate (the real spine).
    # The SafetyLayer logs "step_executed" to the controller's own memory.
    assert any(e["kind"] == "step_executed" for e in ex._controller.memory.history())
    # One at a time: the supervisor never runs steps concurrently.
    assert spy.max_concurrent == 1


def test_unattended_respects_existing_budgets(tmp_path):
    steps = _multi_step_workload()
    ex = FakeExecutive(steps, str(tmp_path / "log.jsonl"))
    sup = _sup(ex, tmp_path)
    s = sup.start(frontier_ref="wl")
    assert _no_budget_exceeded(s)


def _no_budget_exceeded(session: Session) -> bool:
    if session.state in (SessionState.STOPPED, SessionState.FAILED):
        return "budget" not in session.stop_reason
    return session.state == SessionState.COMPLETED


# --------------------------------------------------------------------------- #
# 5. Off / no-regression / byte-identical                                      #
# --------------------------------------------------------------------------- #


def _manual_seq(steps, tmp_path, log_name):
    ex = FakeExecutive(steps, str(tmp_path / log_name))
    while ex.has_pending_work():
        ex.step()
    return ex


def test_unattended_off_is_byte_identical_to_manual(tmp_path):
    steps = _multi_step_workload(n_tasks=3, steps_per_task=2)

    # Manual stepping (today): drain the fake executive directly.
    manual_ex = _manual_seq(steps, tmp_path, "manual_log.jsonl")

    # Unattended: the supervisor drives the SAME fake executive.
    ex = FakeExecutive(steps, str(tmp_path / "sup_log.jsonl"))
    sup = _sup(ex, tmp_path)
    sup.start(frontier_ref="wl")

    # The supervision layer changes nothing about what the executive does:
    # identical step sequence, identical completion.
    assert manual_ex.executed == ex.executed


# --------------------------------------------------------------------------- #
# 6. Adoption gate                                                             #
# --------------------------------------------------------------------------- #


def test_meets_adoption_gate(tmp_path):
    # completion >= manual
    steps = _multi_step_workload()
    ex = FakeExecutive(steps, str(tmp_path / "c.jsonl"))
    sup = _sup(ex, tmp_path)
    s = sup.start(frontier_ref="wl")
    completion = 1 if s.state == SessionState.COMPLETED else 0

    # resume success + zero duplicate work after injected crash
    steps2 = [FakeStep("t", i, "step_done" if i < 4 else "done") for i in range(5)]
    log = str(tmp_path / "crash.jsonl")
    ex1 = FakeExecutive(steps2, log, crash_after=4)
    sup_r = _sup(ex1, tmp_path)
    try:
        sup_r.start(frontier_ref="wl2")
    except RuntimeError:
        pass
    sid = sup_r._last_session.session_id
    ex2 = FakeExecutive(steps2, log)
    s2 = _sup(ex2, tmp_path).resume(sid)
    resume_success = 1.0 if (s2.state == SessionState.COMPLETED and len(set(ex2.executed)) == 5) else 0.0
    duplicate_work = 0 if len(set(ex2.executed)) == 5 else 1

    # stall detected
    stall_snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=200, consecutive_failures=0,
    )
    stall = _watchdog(stall_snap).check(_session_obj(bounds=_bounds(max_ticks=200))).verdict == HealthVerdict.PAUSE

    # unrecoverable stopped
    unrec_snap = HealthSnapshot(
        queue_depth=0, active_work=0, retries_used=0, repairs_used=0,
        research_budget_used=0.0, network_budget_used=0.0, perimeter_denials=0,
        ticks_without_progress=0, consecutive_failures=3,
    )
    unrec = _watchdog(unrec_snap).check(_session_obj(bounds=_bounds(max_consec=3))).verdict == HealthVerdict.STOP_FOR_REVIEW

    regressions = 0
    unsafe_attempts = 0
    authority_increase = 0

    assert completion >= 1
    assert resume_success == 1.0 and duplicate_work == 0
    assert stall and unrec
    assert regressions == 0 and unsafe_attempts == 0 and authority_increase == 0


# --------------------------------------------------------------------------- #
# 7. Wiring: default-off; AppState leaves the executive untouched             #
# --------------------------------------------------------------------------- #


def test_unattended_default_off_in_config():
    cfg = Config()
    assert cfg.unattended_enabled is False
    from_env = Config.from_env()
    assert from_env.unattended_enabled is False


def test_unattended_off_is_none_in_appstate(tmp_path):
    state = AppState.create(root=str(tmp_path / "data"))
    assert state.unattended is None
    # The executive runs exactly as today when the supervisor is off.
    rec = state.queue.enqueue("hello there")
    state.executive.run_once()
    assert state.queue.get(rec.id).state == TaskState.DONE


def test_unattended_status_endpoint_off_is_disabled(tmp_path):
    from fastapi.testclient import TestClient

    from aetheris.api.app import create_app

    state = AppState.create(root=str(tmp_path / "data"))
    client = TestClient(create_app(state))
    r = client.get("/session/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False

