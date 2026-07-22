"""Unified Trace Envelope & Deterministic Replay — pure read-only package.

No imports from other aetheris packages.  No filesystem, network, process,
tool, SafetyLayer, NetworkPerimeter, planner, executive, config mutator, or
store writer references.
"""
from __future__ import annotations

from .canonical import canonical_json, sha256_hex
from .model import (
    EvidenceRef,
    Provenance,
    ReplayContext,
    ReplayFailure,
    ReplayResult,
    SourceLocator,
    TraceEnvelope,
    TraceUnknown,
    TraceValue,
)
from .replay import ReplayEngine
from .view import TraceView, render_summary, render_json

__all__ = [
    "canonical_json",
    "sha256_hex",
    "EvidenceRef",
    "Provenance",
    "ReplayContext",
    "ReplayFailure",
    "ReplayResult",
    "SourceLocator",
    "TraceEnvelope",
    "TraceUnknown",
    "TraceValue",
    "ReplayEngine",
    "TraceView",
    "render_summary",
    "render_json",
]
