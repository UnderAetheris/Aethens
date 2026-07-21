"""AST-based parser for Python files.

Extracts deterministic, structured facts from source code:
- Symbol definitions (functions, classes, methods, assignments)
- Import edges
- Exported symbols (top-level public / __all__)
- Cross-references (where a symbol is used)
- Test file detection and target inference
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from .model import FileFacts, Symbol, SymbolRef


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _module_from_path(root: Path, path: Path) -> str:
    """Derive dotted module path from file path relative to root."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return path.stem
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = rel.stem
    return ".".join(p for p in parts if p)


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") and path.suffix == ".py"


def _infer_test_target(path: Path, root: Path) -> str | None:
    """Best-effort: infer which module a test file exercises."""
    if not _is_test_file(path):
        return None
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "test_" + rel.stem + ".py":
        parts[-1] = rel.stem + ".py"
    elif parts[-1].startswith("test_"):
        parts[-1] = parts[-1][5:]
    mod = ".".join(p for p in parts if p.endswith(".py"))
    mod = mod[:-3]  # strip .py
    return mod or None


def _extract_exports(tree: ast.AST, module: str) -> tuple[str, ...]:
    """Extract exported symbol names from __all__ or top-level public names."""
    all_names: set[str] = set()
    top_level_names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_names.add(elt.value)
                elif isinstance(target, ast.Name) and not target.id.startswith("_"):
                    top_level_names.append(target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                top_level_names.append(node.name)
    if all_names:
        return tuple(sorted(all_names))
    return tuple(sorted(set(top_level_names)))


def _extract_symbols(
    tree: ast.AST, module: str, path_str: str
) -> tuple[Symbol, ...]:
    """Extract symbol definitions from an AST."""
    symbols: list[Symbol] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            ref = SymbolRef(path=path_str, line=node.lineno)
            symbols.append(Symbol(
                name=node.name,
                kind="function",
                module=module,
                definition=ref,
            ))
        elif isinstance(node, ast.ClassDef):
            ref = SymbolRef(path=path_str, line=node.lineno)
            symbols.append(Symbol(
                name=node.name,
                kind="class",
                module=module,
                definition=ref,
            ))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_"):
                        continue
                    mref = SymbolRef(path=path_str, line=item.lineno)
                    symbols.append(Symbol(
                        name=f"{node.name}.{item.name}",
                        kind="method",
                        module=module,
                        definition=mref,
                    ))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    ref = SymbolRef(path=path_str, line=node.lineno)
                    symbols.append(Symbol(
                        name=target.id,
                        kind="variable",
                        module=module,
                        definition=ref,
                    ))
    return tuple(symbols)


def _extract_imports(tree: ast.AST) -> tuple[str, ...]:
    """Extract imported module names from an AST."""
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod:
                    imports.add(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split(".")[0]
                if mod:
                    imports.add(mod)
    return tuple(sorted(imports))


def _extract_uses(tree: ast.AST, symbols: tuple[Symbol, ...], path_str: str) -> dict[str, list[SymbolRef]]:
    """Find where each symbol is used (cross-references)."""
    symbol_names = {s.name: s for s in symbols}
    uses_map: dict[str, list[SymbolRef]] = {name: [] for name in symbol_names}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in symbol_names:
            uses_map[node.id].append(SymbolRef(path=path_str, line=node.lineno))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            fqn = f"{node.value.id}.{node.attr}"
            if fqn in symbol_names:
                uses_map[fqn].append(SymbolRef(path=path_str, line=node.lineno))
    return uses_map


def parse_file(root: Path, path: Path) -> FileFacts | None:
    """Parse a single Python file into FileFacts, or None if not parseable."""
    if path.suffix != ".py":
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return FileFacts(
            path=path.relative_to(root).as_posix(),
            content_hash=_content_hash(text),
            module=_module_from_path(root, path),
            is_test=_is_test_file(path),
            tests_target=_infer_test_target(path, root),
        )
    path_str = path.relative_to(root).as_posix()
    module = _module_from_path(root, path)
    symbols = _extract_symbols(tree, module, path_str)
    imports = _extract_imports(tree)
    uses_map = _extract_uses(tree, symbols, path_str)
    enriched_symbols = []
    for sym in symbols:
        enriched_symbols.append(sym.__class__(
            name=sym.name,
            kind=sym.kind,
            module=sym.module,
            definition=sym.definition,
            exported=sym.name in _extract_exports(tree, module),
            uses=tuple(uses_map.get(sym.name, [])),
        ))
    return FileFacts(
        path=path_str,
        content_hash=_content_hash(text),
        module=module,
        symbols=tuple(enriched_symbols),
        imports=imports,
        is_test=_is_test_file(path),
        tests_target=_infer_test_target(path, root),
    )
