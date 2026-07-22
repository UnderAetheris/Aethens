"""Read-only trace view."""
from __future__ import annotations

import json

from .model import (
    ReplayResult,
)


def render_summary(result: ReplayResult) -> str:
    lines = [
        f"trace_id: {result.trace_id or 'unknown'}",
        f"status: {result.status}",
        f"achieved_level: {result.achieved_level}",
        f"events: {len(result.ordered_events)}",
        f"unknowns: {len(result.unknowns)}",
        f"failures: {len(result.failures)}",
    ]
    if result.failures:
        lines.append("failures:")
        for f in result.failures:
            lines.append(f"  - {f.code}: {f.why}")
    if result.unknowns:
        lines.append("unknowns:")
        for u in result.unknowns:
            lines.append(f"  - {u.code}: {u.reason}")
    return "\n".join(lines)


def render_json(result: ReplayResult) -> str:
    obj = {
        "status": result.status,
        "achieved_level": result.achieved_level,
        "trace_id": result.trace_id,
        "event_count": len(result.ordered_events),
        "reconstructed_state": result.reconstructed_state,
        "failures": [
            {
                "code": f.code,
                "event_id": f.event_id,
                "source_id": f.source_id,
                "why": f.why,
                "required_level": f.required_level,
                "remediation": f.remediation,
            }
            for f in result.failures
        ],
        "unknowns": [
            {
                "code": u.code,
                "field": u.field,
                "reason": u.reason,
                "required_for": u.required_for,
            }
            for u in result.unknowns
        ],
        "input_fingerprint": result.input_fingerprint,
        "result_fingerprint": result.result_fingerprint,
    }
    return json.dumps(obj, indent=2, sort_keys=True)


class TraceView:
    """Read-only trace view."""

    def __init__(self, result: ReplayResult) -> None:
        self._result = result

    @property
    def result(self) -> ReplayResult:
        return self._result

    def summary(self) -> str:
        return render_summary(self._result)

    def json(self) -> str:
        return render_json(self._result)
