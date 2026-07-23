"""Deterministic read-only replay engine.

Replay reconstructs persisted logical state only.  It never executes tools,
never reaches the network, never mutates runtime state.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .canonical import canonical_json, sha256_str
from .model import (
    JsonValue,
    ReplayContext,
    ReplayFailure,
    ReplayResult,
    TraceEnvelope,
    TraceUnknown,
)


def _is_external_root(event_id: str) -> bool:
    return event_id.startswith(("root_", "trace_", "session_", "global_"))


# ---------------------------------------------------------------------------
# Pure reducer protocol
# ---------------------------------------------------------------------------

Reducer = Callable[[dict[str, JsonValue], TraceEnvelope], dict[str, JsonValue]]


def _route_task_outcome(env: TraceEnvelope) -> bool:
    return env.subsystem == "memory" and env.event_type in (
        "action_allowed", "action_blocked", "action_preview", "step_result",
    )


def _route_plan_state(env: TraceEnvelope) -> bool:
    return env.subsystem == "planner" and env.event_type == "plan_snapshot"


def _route_hierarchy_state(env: TraceEnvelope) -> bool:
    return env.subsystem == "hierarchy" and env.event_type == "goal_transition"


def _route_unattended_state(env: TraceEnvelope) -> bool:
    return env.subsystem == "unattended" and env.event_type in (
        "session_stopped", "session_checkpoint",
    )


def _route_research_summary(env: TraceEnvelope) -> bool:
    return env.subsystem == "research"


def _route_adoption_summary(env: TraceEnvelope) -> bool:
    return env.capability_id in ("memory", "experience_recording", "skills")


def _route_change_set_summary(env: TraceEnvelope) -> bool:
    return env.event_type == "change_set"


def _route_rollback_summary(env: TraceEnvelope) -> bool:
    return env.event_type == "rollback_receipt"


# ---------------------------------------------------------------------------
# Built-in reducers
# ---------------------------------------------------------------------------

def reduce_task_outcome(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_task_outcome(env):
        return state
    task_id = env.task_id or "unknown"
    task_state = dict(state.get("tasks", {}).get(task_id, {}))
    kind = env.event_type
    data: dict[str, Any] = {}
    if hasattr(env.outcome, "value") and env.outcome.value is not None:
        raw = env.outcome.value
        if isinstance(raw, str):
            data["last_kind"] = raw
        elif isinstance(raw, dict):
            data.update(raw)
        elif isinstance(raw, list):
            data["last_kind_list"] = raw
    if kind in ("action_allowed", "action_blocked", "action_preview"):
        task_state["last_memory_kind"] = kind
        task_state.update(data)
    elif kind == "step_result":
        task_state["last_step_result"] = data
    task_state.setdefault("events", [])
    task_state["events"].append(env.event_id)
    new_tasks = dict(state.get("tasks", {}))
    new_tasks[task_id] = task_state
    state["tasks"] = new_tasks
    return state


def reduce_plan_state(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_plan_state(env):
        return state
    plan_id = env.plan_id or "unknown"
    plan_state = dict(state.get("plans", {}).get(plan_id, {}))
    if env.event_type == "plan_snapshot":
        raw = env.outcome.value if env.outcome and env.outcome.value else []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        if isinstance(raw, list):
            plan_state["steps"] = raw
    plan_state.setdefault("events", [])
    plan_state["events"].append(env.event_id)
    new_plans = dict(state.get("plans", {}))
    new_plans[plan_id] = plan_state
    state["plans"] = new_plans
    return state


def reduce_hierarchy_state(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_hierarchy_state(env):
        return state
    goal_id = env.goal_id or "unknown"
    goal_state = dict(state.get("goals", {}).get(goal_id, {}))
    step_id = env.step_id or "unknown"
    step_state = dict(goal_state.get("subgoals", {}).get(step_id, {}))
    if env.event_type == "goal_transition":
        to_state = env.outcome.value if env.outcome and env.outcome.value else "unknown"
        step_state["final_state"] = to_state
    step_state.setdefault("events", [])
    step_state["events"].append(env.event_id)
    subgoals = dict(goal_state.get("subgoals", {}))
    subgoals[step_id] = step_state
    goal_state["subgoals"] = subgoals
    new_goals = dict(state.get("goals", {}))
    new_goals[goal_id] = goal_state
    state["goals"] = new_goals
    return state


def reduce_unattended_state(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_unattended_state(env):
        return state
    session_id = env.session_id or "unknown"
    session_state = dict(state.get("sessions", {}).get(session_id, {}))
    if env.event_type == "session_stopped":
        final_state = env.outcome.value if env.outcome and env.outcome.value else "unknown"
        session_state["terminal_state"] = final_state
    elif env.event_type == "session_checkpoint":
        session_state["last_checkpoint"] = True
    session_state.setdefault("events", [])
    session_state["events"].append(env.event_id)
    new_sessions = dict(state.get("sessions", {}))
    new_sessions[session_id] = session_state
    state["sessions"] = new_sessions
    return state


def reduce_research_summary(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_research_summary(env):
        return state
    kinds: dict[str, int] = dict(state.get("research_kind_counts", {}))
    kind = env.event_type
    kinds[kind] = kinds.get(kind, 0) + 1
    state["research_kind_counts"] = kinds
    return state


def reduce_adoption_summary(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_adoption_summary(env):
        return state
    capability_id = env.capability_id or "unknown"
    caps = dict(state.get("adoption", {}))
    entry = dict(caps.get(capability_id, {}))
    entry["events"] = entry.get("events", []) + [env.event_id]
    caps[capability_id] = entry
    state["adoption"] = caps
    return state


def reduce_change_set_summary(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_change_set_summary(env):
        return state
    change_kind = env.outcome.value if env.outcome and env.outcome.value else "unknown"
    kinds: dict[str, int] = dict(state.get("change_kind_counts", {}))
    kinds[change_kind] = kinds.get(change_kind, 0) + 1
    state["change_kind_counts"] = kinds
    caps = dict(state.get("change_capabilities", {}))
    cap = env.capability_id or "unknown"
    caps[cap] = caps.get(cap, 0) + 1
    state["change_capabilities"] = caps
    return state


def reduce_rollback_summary(
    state: dict[str, JsonValue], env: TraceEnvelope
) -> dict[str, JsonValue]:
    if not _route_rollback_summary(env):
        return state
    rollback_kind = env.outcome.value if env.outcome and env.outcome.value else "unknown"
    kinds: dict[str, int] = dict(state.get("rollback_kind_counts", {}))
    kinds[rollback_kind] = kinds.get(rollback_kind, 0) + 1
    state["rollback_kind_counts"] = kinds
    return state


_REDUCER_ROUTES: dict[str, Callable[[TraceEnvelope], bool]] = {
    "task_outcome": _route_task_outcome,
    "plan_state": _route_plan_state,
    "hierarchy_state": _route_hierarchy_state,
    "unattended_state": _route_unattended_state,
    "research_summary": _route_research_summary,
    "adoption_summary": _route_adoption_summary,
    "change_set_summary": _route_change_set_summary,
    "rollback_summary": _route_rollback_summary,
}

_REGISTERED_REDUCERS: dict[str, Reducer] = {
    "task_outcome": reduce_task_outcome,
    "plan_state": reduce_plan_state,
    "hierarchy_state": reduce_hierarchy_state,
    "unattended_state": reduce_unattended_state,
    "research_summary": reduce_research_summary,
    "adoption_summary": reduce_adoption_summary,
    "change_set_summary": reduce_change_set_summary,
    "rollback_summary": reduce_rollback_summary,
}


# ---------------------------------------------------------------------------
# Lineage / ordering
# ---------------------------------------------------------------------------

@dataclass
class _Edge:
    src: str
    dst: str


def _topological_sort(
    nodes: list[str], edges: list[_Edge]
) -> tuple[list[str], list[str] | None]:
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.src not in in_degree:
            in_degree[e.src] = 0
        if e.dst not in in_degree:
            in_degree[e.dst] = 0
        children[e.src].append(e.dst)
        in_degree[e.dst] += 1
    queue = deque(sorted(n for n in nodes if in_degree[n] == 0))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in sorted(children[node]):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    if len(order) != len(set(nodes)):
        cycle = _find_cycle(nodes, edges)
        return [], cycle
    return order, None


def _find_cycle(nodes: list[str], edges: list[_Edge]) -> list[str] | None:
    visited: set[str] = set()
    rec_stack: set[str] = set()
    parent_map: dict[str, str] = {}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adj[e.src].append(e.dst)

    def dfs(node: str) -> list[str] | None:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                result = dfs(neighbor)
                if result:
                    return result
            elif neighbor in rec_stack:
                cycle = [neighbor, node]
                cur = node
                while cur != neighbor:
                    cur = parent_map.get(cur, neighbor)
                    if cur not in cycle:
                        cycle.append(cur)
                return list(reversed(cycle))
        rec_stack.discard(node)
        return None

    for node in sorted(set(nodes)):
        if node not in visited:
            parent_map[node] = node
            result = dfs(node)
            if result:
                return result
    return None


# ---------------------------------------------------------------------------
# ReplayEngine
# ---------------------------------------------------------------------------

class ReplayEngine:
    """Deterministic replay over a set of projected envelopes."""

    def __init__(self, reducers: dict[str, Reducer] | None = None) -> None:
        self._reducers = reducers or dict(_REGISTERED_REDUCERS)

    def replay(
        self,
        envelopes: list[TraceEnvelope],
        context: ReplayContext,
    ) -> ReplayResult:
        failures: list[ReplayFailure] = []
        unknowns: list[TraceUnknown] = []

        seen_ids: set[str] = set()
        id_map: dict[str, TraceEnvelope] = {}
        edges: list[_Edge] = []

        for env in envelopes:
            if env.event_id in seen_ids:
                failures.append(ReplayFailure(
                    code="malformed_record",
                    event_id=env.event_id,
                    source_id=env.source.stream_id,
                    why="duplicate event_id detected",
                    required_level=1,
                    remediation="deduplicate source records",
                ))
            seen_ids.add(env.event_id)
            id_map[env.event_id] = env

            if env.parent_event_id:
                if env.parent_event_id not in id_map and not _is_external_root(env.parent_event_id):
                    failures.append(ReplayFailure(
                        code="missing_parent",
                        event_id=env.event_id,
                        source_id=env.source.stream_id,
                        why=f"parent_event_id {env.parent_event_id} not in envelope set",
                        required_level=2,
                        remediation="ensure parent event is included in replay input",
                    ))
                edges.append(_Edge(src=env.parent_event_id, dst=env.event_id))
            for cid in env.cause_event_ids:
                if cid not in id_map and not _is_external_root(cid):
                    failures.append(ReplayFailure(
                        code="missing_cause",
                        event_id=env.event_id,
                        source_id=env.source.stream_id,
                        why=f"cause_event_id {cid} not in envelope set",
                        required_level=2,
                        remediation="ensure cause event is included in replay input",
                    ))
                edges.append(_Edge(src=cid, dst=env.event_id))

            unknowns.extend(env.unknowns)

        cycle_nodes = _topological_sort(
            [e.event_id for e in envelopes], edges
        )[1]
        if cycle_nodes:
            failures.append(ReplayFailure(
                code="causal_cycle",
                event_id=cycle_nodes[0] if cycle_nodes else None,
                source_id=None,
                why="causal cycle detected in envelope graph",
                required_level=2,
                remediation="remove or break cycle",
            ))
            return ReplayResult(
                status="invalid",
                achieved_level=0,
                trace_id=context.expected_trace_id,
                ordered_events=tuple(sorted(envelopes, key=lambda e: e.event_id)),
                reconstructed_state={},
                failures=tuple(failures),
                unknowns=tuple(unknowns),
                input_fingerprint="",
                result_fingerprint="",
            )

        topo_order, _ = _topological_sort(
            [e.event_id for e in envelopes], edges
        )
        if topo_order:
            id_by_event = {e.event_id: e for e in envelopes}
            ordered = [id_by_event[eid] for eid in topo_order if eid in id_by_event]
        else:
            ordered = sorted(envelopes, key=lambda e: (
                e.stream_sequence or 0,
                e.event_id,
            ))

        level = 1
        if not failures:
            level = 2
            if not unknowns:
                level = 3
                # Level 4 requires event-type-specific deterministic decision verifiers.
                # No verifier means unsupported, not level 4.
                if self._reducers:
                    pass

        status: Literal["complete", "incomplete", "invalid", "unsupported"]
        if failures:
            status = "incomplete" if level >= 2 else "invalid"
        else:
            if level >= 3 and not self._reducers:
                status = "unsupported"
            else:
                status = "complete"

        reconstructed: dict[str, JsonValue] = {}
        for env in ordered:
            for name, reducer in self._reducers.items():
                route = _REDUCER_ROUTES.get(name)
                if route is not None and not route(env):
                    continue
                reconstructed = reducer(reconstructed, env)

        input_fp = sha256_str(
            canonical_json({
                "revision": context.revision.state,
                "expected_trace_id": context.expected_trace_id,
                "strict": context.strict,
                "event_ids": [e.event_id for e in ordered],
            })
        )
        result_fp = sha256_str(
            canonical_json({
                "reconstructed": reconstructed,
                "failure_codes": [f.code for f in failures],
                "unknown_codes": [u.code for u in unknowns],
            })
        )

        return ReplayResult(
            status=status,
            achieved_level=level,
            trace_id=context.expected_trace_id,
            ordered_events=tuple(ordered),
            reconstructed_state=reconstructed,
            failures=tuple(failures),
            unknowns=tuple(unknowns),
            input_fingerprint=input_fp,
            result_fingerprint=result_fp,
        )
