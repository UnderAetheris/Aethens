from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    safe_mode: bool = True
    log_path: str = "aetheris_memory.jsonl"
    workspace_root: str = "."
    allowed_shell_commands: tuple[str, ...] = ("echo", "ls", "pwd", "cat")
    reflection_enabled: bool = True  # AETHERIS_REFLECTION=0 to disable

    @classmethod
    def from_env(cls) -> "Config":
        raw = os.getenv("AETHERIS_SHELL_ALLOWLIST", "")
        allow = tuple(c.strip() for c in raw.split(",") if c.strip())
        return cls(
            safe_mode=os.getenv("AETHERIS_SAFE_MODE", "1") != "0",
            log_path=os.getenv("AETHERIS_LOG_PATH", "aetheris_memory.jsonl"),
            workspace_root=os.getenv("AETHERIS_WORKSPACE_ROOT", "."),
            allowed_shell_commands=allow or ("echo", "ls", "pwd", "cat"),
            reflection_enabled=os.getenv("AETHERIS_REFLECTION", "1") != "0",
        )
