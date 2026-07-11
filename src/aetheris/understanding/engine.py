"""Repository Understanding Engine v0.

Read-only semantic model of the workspace.  Never edits code, never executes,
never calls tools.  Builds a deterministic, AST-derived structured model;
others query it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import FileFacts, ModuleNode, RepoModel, Symbol, SymbolRef


class ScanReport:
    """Outcome of one scan episode."""

    def __init__(self, changed: list[str], removed: list[str], version: int) -> None:
        self.changed = changed
        self.removed = removed
        self.version = version
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "removed": self.removed,
            "version": self.version,
            "timestamp": self.timestamp,
        }


class RepoUnderstanding:
    """Read-only semantic model of the workspace.

    The only mutator is ``scan()``, which writes only the model/journal,
    never source.  All other methods are pure reads.
    """

    def __init__(self, root: str, model_path: str) -> None:
        self._root = Path(root).resolve()
        self._model_path = Path(model_path)
        self._journal_path = Path(str(model_path) + ".journal.jsonl")
        self._model = self._load_or_empty()

    # ------------------------------------------------------------------ #
    # Build / update (the only write path)                               #
    # ------------------------------------------------------------------ #

    def scan(self) -> ScanReport:
        """Incremental: re-parse only files whose content hash changed."""
        changed, removed = self._diff_filesystem()
        for rel_path in changed:
            abs_path = self._root / rel_path
            facts = self._parse_file(abs_path)
            if facts is not None:
                self._model.files[rel_path] = facts
            elif rel_path in self._model.files:
                del self._model.files[rel_path]
        for rel_path in removed:
            self._model.files.pop(rel_path, None)
        self._rederive_indices()
        self._detect_project_facts()
        self._model.version += 1
        self._model.root = str(self._root)
        self._persist()
        report = ScanReport(changed=changed, removed=removed, version=self._model.version)
        self._journal_append(report)
        return report

    def version(self) -> int:
        return self._model.version

    def scan_history(self) -> list[dict[str, Any]]:
        if not self._journal_path.exists():
            return []
        out = []
        with open(self._journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    # ------------------------------------------------------------------ #
    # Query interface (the ENTIRE public surface for consumers)           #
    # ------------------------------------------------------------------ #

    def defines(self, name: str) -> list[Symbol]:
        """All definitions of a symbol, with file+line provenance."""
        return list(self._model.symbols.get(name, []))

    def uses(self, name: str) -> list[SymbolRef]:
        """All cross-references where a symbol is used."""
        refs: list[SymbolRef] = []
        for facts in self._model.files.values():
            for sym in facts.symbols:
                if sym.name == name:
                    refs.extend(sym.uses)
        return refs

    def module_of(self, name: str) -> str | None:
        """The module where a symbol is defined (first definition)."""
        syms = self._model.symbols.get(name)
        if syms:
            return syms[0].module
        return None

    def exporting_module(self, name: str) -> str | None:
        """Which module exports a symbol (public / __all__)."""
        for facts in self._model.files.values():
            for sym in facts.symbols:
                if sym.name == name and sym.exported:
                    return sym.module
        return None

    def dependents_of(self, name: str) -> list[str]:
        """Modules that import/use a symbol (who breaks if it changes)."""
        deps: list[str] = []
        for facts in self._model.files.values():
            for sym in facts.symbols:
                if sym.name == name and sym.uses:
                    deps.append(facts.module)
        return list(set(deps))

    def tests_for(self, path: str) -> list[str]:
        """Test files that exercise the given implementation path."""
        tests: list[str] = []
        target_mod = Path(path).stem
        for facts in self._model.files.values():
            if facts.is_test and facts.tests_target:
                if target_mod in facts.tests_target:
                    tests.append(facts.path)
        return tests

    def find_helper(self, intent: str) -> list[Symbol]:
        """Deterministic helper lookup: match intent against symbol names."""
        intent_lower = intent.lower()
        candidates: list[Symbol] = []
        for syms in self._model.symbols.values():
            for sym in syms:
                if sym.kind in ("function", "method") and sym.exported:
                    if intent_lower in sym.name.lower():
                        candidates.append(sym)
        candidates.sort(key=lambda s: s.name)
        return candidates

    def exported_api(self, module: str) -> list[str]:
        """Public symbols exported by a module."""
        names: list[str] = []
        for facts in self._model.files.values():
            if facts.module == module:
                for sym in facts.symbols:
                    if sym.exported:
                        names.append(sym.name)
        return sorted(set(names))

    def project_facts(self) -> dict[str, Any]:
        """Project-level facts: language, build system, entrypoints, summary."""
        return {
            "language": self._model.language,
            "build_system": self._model.build_system,
            "entrypoints": list(self._model.entrypoints),
            "readme_summary": self._model.readme_summary,
            "architecture_summary": self._model.architecture_summary,
            "version": self._model.version,
        }

    def module_nodes(self) -> dict[str, ModuleNode]:
        """Module-level dependency graph."""
        nodes: dict[str, ModuleNode] = {}
        for facts in self._model.files.values():
            nodes[facts.module] = ModuleNode(
                module=facts.module,
                path=facts.path,
                imports=facts.imports,
                exported=tuple(s.name for s in facts.symbols if s.exported),
            )
        return nodes

    # ------------------------------------------------------------------ #
    # Internal: parsing, persistence, diffing                            #
    # ------------------------------------------------------------------ #

    def _parse_file(self, path: Path) -> FileFacts | None:
        from .parser import parse_file
        return parse_file(self._root, path)

    def _load_or_empty(self) -> RepoModel:
        if self._model_path.exists():
            try:
                with open(self._model_path, "r", encoding="utf-8") as f:
                    return RepoModel.from_dict(json.load(f))
            except (json.JSONDecodeError, KeyError):
                pass
        return RepoModel(root=str(self._root))

    def _persist(self) -> None:
        tmp = Path(str(self._model_path) + ".tmp")
        tmp.write_text(
            json.dumps(self._model.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(self._model_path)

    def _journal_append(self, report: ScanReport) -> None:
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), default=str) + "\n")

    def _diff_filesystem(self) -> tuple[list[str], list[str]]:
        """Compare filesystem to model; return (changed, removed) relative paths."""
        current_paths: set[str] = set()
        changed: list[str] = []
        if self._root.exists():
            for abs_path in self._root.rglob("*.py"):
                if abs_path.is_file():
                    rel = abs_path.relative_to(self._root).as_posix()
                    current_paths.add(rel)
                    try:
                        text = abs_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                    facts = self._model.files.get(rel)
                    if facts is None or facts.content_hash != new_hash:
                        changed.append(rel)
        removed = [p for p in self._model.files if p not in current_paths]
        return changed, removed

    def _rederive_indices(self) -> None:
        """Rebuild symbols and call_graph indices from files."""
        self._model.symbols.clear()
        for facts in self._model.files.values():
            for sym in facts.symbols:
                self._model.symbols.setdefault(sym.name, []).append(sym)
        self._model.call_graph.clear()

    def _detect_project_facts(self) -> None:
        """Detect language, build system, entrypoints, README."""
        if any(f.path.endswith("pyproject.toml") for f in self._model.files.values()):
            self._model.build_system = "pyproject"
        elif any(f.path.endswith("setup.py") for f in self._model.files.values()):
            self._model.build_system = "setup.py"
        readmes = [f for f in self._model.files if f.lower().startswith("readme")]
        if readmes:
            self._model.readme_summary = f"README present: {readmes[0]}"
        entrypoints: list[str] = []
        for facts in self._model.files.values():
            for sym in facts.symbols:
                if sym.name in ("main", "run", "start", "serve", "cli") and sym.kind == "function":
                    entrypoints.append(f"{facts.module}:{sym.name}")
        self._model.entrypoints = tuple(entrypoints[:10])
