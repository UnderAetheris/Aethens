"""Read-only, root-bounded index of the workspace.

Never executes.  Never sees outside the root.  Provides:
  - files()      → relative paths under root
  - tests()      → test_*.py files
  - search(term) → (path, line, text) matches
  - _contains(p) → containment check (same semantics as path_within_root)
"""
from __future__ import annotations

from pathlib import Path


class WorkspaceIndex:
    """Bounded read-only map of the repo."""

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()

    def files(self) -> list[str]:
        """Relative file paths under root (directories excluded)."""
        if not self._root.exists():
            return []
        out = []
        for p in self._root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self._root).as_posix()
                out.append(rel)
        out.sort()
        return out

    def tests(self) -> list[str]:
        """Files whose basename starts with test_ and ends with .py."""
        return [f for f in self.files()
                if f.startswith("test_") and f.endswith(".py")]

    def search(self, term: str) -> list[tuple[str, int, str]]:
        """Grep-like search: (relative_path, line_number, line_text)."""
        results = []
        for rel in self.files():
            try:
                path = self._root / rel
                text = path.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if term in line:
                        results.append((rel, i, line.strip()))
            except OSError:
                continue
        results.sort()
        return results

    def _contains(self, p: str) -> bool:
        """Return True if the resolved path is inside the workspace root."""
        try:
            rp = Path(p).resolve()
        except OSError:
            return False
        return rp == self._root or self._root in rp.parents
