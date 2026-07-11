from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from .base import Tool, ToolRegistry

_BAK_SUFFIX = ".aetheris.bak"


def _echo(text: str) -> str:
    return text


def _read_file(arg: str) -> str:
    path = Path(json.loads(arg)["path"])
    return path.read_text(encoding="utf-8")


def _list_dir(arg: str) -> str:
    path = Path(json.loads(arg)["path"])
    return "\n".join(sorted(p.name for p in path.iterdir()))


def _write_file(arg: str) -> str:
    data = json.loads(arg)
    path = Path(data["path"])
    content = data["content"]
    backup = path.with_name(path.name + _BAK_SUFFIX)
    snapshot = {
        "existed": path.exists(),
        "content": path.read_text(encoding="utf-8") if path.exists() else None,
    }
    backup.write_text(json.dumps(snapshot), encoding="utf-8")
    path.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


def _undo_write_file(arg: str) -> None:
    path = Path(json.loads(arg)["path"])
    backup = path.with_name(path.name + _BAK_SUFFIX)
    if not backup.exists():
        return
    snapshot = json.loads(backup.read_text(encoding="utf-8"))
    if snapshot["existed"]:
        path.write_text(snapshot["content"], encoding="utf-8")
    elif path.exists():
        path.unlink()
    backup.unlink()


def _edit_file(arg: str) -> str:
    data = json.loads(arg)
    path = Path(data["path"])
    find = data["find"]
    replace = data["replace"]
    backup = path.with_name(path.name + _BAK_SUFFIX)
    snapshot = {
        "existed": path.exists(),
        "content": path.read_text(encoding="utf-8") if path.exists() else None,
    }
    backup.write_text(json.dumps(snapshot), encoding="utf-8")
    content = path.read_text(encoding="utf-8")
    if find not in content:
        raise ValueError(f"pattern '{find}' not found in {path}")
    new_content = content.replace(find, replace, 1)
    path.write_text(new_content, encoding="utf-8")
    return f"edited {path}: replaced '{find}' with '{replace}'"


def _search_content(arg: str) -> str:
    data = json.loads(arg)
    term = data.get("term", "")
    path = data.get("path", ".")
    root = Path(path)
    results = []
    for p in root.rglob("*"):
        if p.is_file():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if term in line:
                    rel = p.relative_to(root).as_posix()
                    results.append(f"{rel}:{i}: {line.strip()}")
    return "\n".join(results) if results else "(no matches)"


def _run_tests(arg: str) -> str:
    data = json.loads(arg)
    cmd = data.get("cmd", "pytest")
    cwd = data.get("cwd", ".")
    return _shell(json.dumps({"cmd": cmd, "cwd": cwd}))


def _run_check(arg: str) -> str:
    data = json.loads(arg)
    cmd = data.get("cmd", "ruff check .")
    cwd = data.get("cwd", ".")
    return _shell(json.dumps({"cmd": cmd, "cwd": cwd}))


def _shell(arg: str) -> str:
    data = json.loads(arg)
    cmd = data["cmd"]
    cwd = data.get("cwd")
    if os.name == "nt":
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=True, cwd=cwd)
    else:
        proc = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=10, cwd=cwd
        )
    return (proc.stdout + proc.stderr).strip()


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(name="echo", description="Return the input unchanged.", run=_echo, safe=True)
    )
    registry.register(
        Tool(
            name="read_file",
            description='Read a file. Arg: {"path": "..."}.',
            run=_read_file,
            safe=True,
        )
    )
    registry.register(
        Tool(
            name="list_dir",
            description='List a directory. Arg: {"path": "..."}.',
            run=_list_dir,
            safe=True,
        )
    )
    registry.register(
        Tool(
            name="write_file",
            description='Write a file. Arg: {"path": "...", "content": "..."}.',
            run=_write_file,
            safe=False,
            undo=_undo_write_file,
        )
    )
    registry.register(
        Tool(
            name="edit_file",
            description='Edit a file by find/replace. Arg: {"path": "...", "find": "...", "replace": "..."}.',
            run=_edit_file,
            safe=False,
            undo=_undo_write_file,
        )
    )
    registry.register(
        Tool(
            name="search_content",
            description='Search for a term in files under a path. Arg: {"term": "...", "path": "..."}.',
            run=_search_content,
            safe=True,
        )
    )
    registry.register(
        Tool(
            name="run_tests",
            description='Run tests. Arg: {"cmd": "pytest ...", "cwd": "..."}.',
            run=_run_tests,
            safe=False,
        )
    )
    registry.register(
        Tool(
            name="run_check",
            description='Run a lint/check command. Arg: {"cmd": "ruff ...", "cwd": "..."}.',
            run=_run_check,
            safe=False,
        )
    )
    registry.register(
        Tool(
            name="shell",
            description='Run an allowlisted shell command. Arg: {"cmd": "..."}.',
            run=_shell,
            safe=False,
        )
    )
    return registry
