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


def _shell(arg: str) -> str:
    cmd = json.loads(arg)["cmd"]
    if os.name == "nt":
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=True)
    else:
        proc = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, timeout=10
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
            name="shell",
            description='Run an allowlisted shell command. Arg: {"cmd": "..."}.',
            run=_shell,
            safe=False,
        )
    )
    return registry
