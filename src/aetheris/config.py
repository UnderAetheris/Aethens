from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    safe_mode: bool = True
    log_path: str = "aetheris_memory.jsonl"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            safe_mode=os.getenv("AETHERIS_SAFE_MODE", "1") != "0",
            log_path=os.getenv("AETHERIS_LOG_PATH", "aetheris_memory.jsonl"),
        )
