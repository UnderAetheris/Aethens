"""Repository model dataclasses for the Understanding Engine.

All facts are deterministic, AST-derived, and trace to a file+line.
No embeddings, no opaque vectors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SymbolRef:
    """A reference to a location in source code."""
    path: str      # file relative to root
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SymbolRef":
        return cls(path=d["path"], line=d["line"])


@dataclass(frozen=True)
class Symbol:
    """A defined symbol (function, class, method, or top-level assignment)."""
    name: str
    kind: str                  # function | class | method | variable
    module: str                # dotted module path (e.g. aetheris.config)
    definition: SymbolRef
    exported: bool = False     # public / in __all__
    uses: tuple[SymbolRef, ...] = ()   # cross-references where it's referenced

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "module": self.module,
            "definition": self.definition.to_dict(),
            "exported": self.exported,
            "uses": [u.to_dict() for u in self.uses],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Symbol":
        return cls(
            name=d["name"],
            kind=d["kind"],
            module=d["module"],
            definition=SymbolRef.from_dict(d["definition"]),
            exported=d.get("exported", False),
            uses=tuple(SymbolRef.from_dict(u) for u in d.get("uses", [])),
        )


@dataclass(frozen=True)
class ModuleNode:
    """A module's contribution: imports it makes, symbols it exports."""
    module: str
    path: str
    imports: tuple[str, ...] = ()
    exported: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "path": self.path,
            "imports": list(self.imports),
            "exported": list(self.exported),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ModuleNode":
        return cls(
            module=d["module"],
            path=d["path"],
            imports=tuple(d.get("imports", [])),
            exported=tuple(d.get("exported", [])),
        )


@dataclass(frozen=True)
class FileFacts:
    """One file's contribution to the model, keyed by content hash."""
    path: str
    content_hash: str
    module: str
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[str, ...] = ()
    is_test: bool = False
    tests_target: str | None = None   # module/path this test exercises

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "module": self.module,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": list(self.imports),
            "is_test": self.is_test,
            "tests_target": self.tests_target,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FileFacts":
        return cls(
            path=d["path"],
            content_hash=d["content_hash"],
            module=d["module"],
            symbols=tuple(Symbol.from_dict(s) for s in d.get("symbols", [])),
            imports=tuple(d.get("imports", [])),
            is_test=d.get("is_test", False),
            tests_target=d.get("tests_target"),
        )


@dataclass
class RepoModel:
    """The persisted semantic model of a repository."""
    version: int = 0
    root: str = ""
    files: dict[str, FileFacts] = field(default_factory=dict)
    symbols: dict[str, list[Symbol]] = field(default_factory=dict)
    call_graph: dict[str, list[str]] = field(default_factory=dict)
    language: str = "python"
    build_system: str = ""
    entrypoints: tuple[str, ...] = ()
    readme_summary: str = ""
    architecture_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": self.root,
            "files": {p: f.to_dict() for p, f in self.files.items()},
            "symbols": {n: [s.to_dict() for s in syms] for n, syms in self.symbols.items()},
            "call_graph": dict(self.call_graph),
            "language": self.language,
            "build_system": self.build_system,
            "entrypoints": list(self.entrypoints),
            "readme_summary": self.readme_summary,
            "architecture_summary": self.architecture_summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RepoModel":
        model = cls(
            version=d.get("version", 0),
            root=d.get("root", ""),
            language=d.get("language", "python"),
            build_system=d.get("build_system", ""),
            entrypoints=tuple(d.get("entrypoints", [])),
            readme_summary=d.get("readme_summary", ""),
            architecture_summary=d.get("architecture_summary", ""),
        )
        model.files = {p: FileFacts.from_dict(f) for p, f in d.get("files", {}).items()}
        model.symbols = {
            n: [Symbol.from_dict(s) for s in syms]
            for n, syms in d.get("symbols", {}).items()
        }
        model.call_graph = d.get("call_graph", {})
        return model
