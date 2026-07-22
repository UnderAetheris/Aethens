"""Read-only CLI for inspecting Aetheris trace envelopes.

Writes only to stdout/stderr.  Never creates cache, index, export, report,
or repair files.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aetheris.trace.adapters import adapter_for
from aetheris.trace.model import (
    ReplayContext,
    SourceLocator,
    TraceValue,
)
from aetheris.trace.replay import ReplayEngine
from aetheris.trace.view import render_json, render_summary


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"_malformed": True, "_raw": line, "_line": lineno})
    return records


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_source(spec: str) -> tuple[SourceLocator, Any]:
    kind, _, rest = spec.partition("=")
    kind = kind.strip().lower()
    rest = rest.strip()
    path = Path(rest)
    if not path.exists():
        raise FileNotFoundError(f"source path does not exist: {path}")
    if kind in ("memory", "jsonl", "knowledge", "experience", "learned"):
        loc = SourceLocator(store_kind="memory_store" if kind == "memory" else "jsonl_store",
                            stream_id=kind, path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "plans":
        loc = SourceLocator(store_kind="plan_store", stream_id="plans", path_hint=rest)
        data = _load_json(path)
        if isinstance(data, dict):
            return loc, data
        return loc, data
    if kind == "research":
        loc = SourceLocator(store_kind="research_journal", stream_id="research", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "hierarchy":
        loc = SourceLocator(store_kind="hierarchy_journal", stream_id="hierarchy", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "unattended":
        loc = SourceLocator(store_kind="unattended_journal", stream_id="unattended", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "understanding":
        loc = SourceLocator(store_kind="understanding_journal", stream_id="understanding", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "reliability":
        loc = SourceLocator(store_kind="reliability_journal", stream_id="reliability", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "change_set":
        loc = SourceLocator(store_kind="change_set", stream_id="change_sets", path_hint=rest)
        return loc, _load_jsonl(path)
    if kind == "rollback_receipt":
        loc = SourceLocator(store_kind="rollback_receipt", stream_id="rollback_receipts", path_hint=rest)
        return loc, _load_jsonl(path)
    raise ValueError(f"unknown source kind: {kind}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aetheris trace inspector")
    ap.add_argument("--source", action="append", default=[], help="kind=path")
    ap.add_argument("--trace-id", default=None, help="expected trace id")
    ap.add_argument("--format", choices=["summary", "json"], default="summary")
    ap.add_argument("--validate-only", action="store_true", help="exit non-zero on validation failure")
    args = ap.parse_args(argv)

    if not args.source:
        ap.print_help()
        return 2

    context = ReplayContext(
        revision=TraceValue(state="unknown", value=None, reason="no revision supplied"),
        config_snapshot=TraceValue(state="unknown", value=None, reason="no config supplied"),
        policy_snapshot=TraceValue(state="unknown", value=None, reason="no policy supplied"),
        evidence_catalog=(),
        source_catalog=(),
        expected_trace_id=args.trace_id,
        strict=True,
    )

    envelopes: list[Any] = []
    failed = False
    for spec in args.source:
        try:
            loc, records = _parse_source(spec)
        except Exception as exc:
            print(f"ERROR: failed to load source {spec}: {exc}", file=sys.stderr)
            failed = True
            continue
        adapter = adapter_for(loc)
        if adapter is None:
            print(f"ERROR: no adapter for source kind {loc.store_kind}", file=sys.stderr)
            failed = True
            continue
        if isinstance(records, list):
            items = records
        elif isinstance(records, dict):
            items = [records]
        else:
            items = [records]
        for idx, rec in enumerate(items):
            src = SourceLocator(
                store_kind=loc.store_kind,
                stream_id=loc.stream_id,
                path_hint=loc.path_hint,
                line_number=idx + 1 if isinstance(records, list) else None,
                record_key=loc.record_key,
                snapshot_version=loc.snapshot_version,
            )
            try:
                projected = adapter.project(src, rec, context)
            except Exception as exc:
                print(f"ERROR: adapter failed on {spec} record {idx}: {exc}", file=sys.stderr)
                failed = True
                continue
            envelopes.extend(projected)

    engine = ReplayEngine()
    result = engine.replay(envelopes, context)

    if args.format == "json":
        output = render_json(result)
    else:
        output = render_summary(result)

    print(output)

    if args.validate_only and (result.failures or result.status != "complete"):
        return 1
    return 1 if failed and args.validate_only else 0


if __name__ == "__main__":
    raise SystemExit(main())
