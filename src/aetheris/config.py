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
    code_loop_enabled: bool = False  # AETHERIS_CODE_LOOP=1 to enable workspace-aware repair

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
            code_loop_enabled=os.getenv("AETHERIS_CODE_LOOP", "0") == "1",
        )


@dataclass(frozen=True)
class PromotionConfig:
    min_recurrence: int = 3            # clamp [2, 20]
    stability_max_repairs: int = 0     # clamp [0, 3]; 0 = only zero-repair plans
    promotion_budget: int = 1          # clamp [1, 5] candidates per idle cycle

    @staticmethod
    def _clamp(val: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, val))

    @classmethod
    def from_env(cls) -> "PromotionConfig":
        return cls(
            min_recurrence=cls._clamp(int(os.getenv("AETHERIS_MIN_RECURRENCE", "3")), 2, 20),
            stability_max_repairs=cls._clamp(int(os.getenv("AETHERIS_STABILITY_MAX_REPAIRS", "0")), 0, 3),
            promotion_budget=cls._clamp(int(os.getenv("AETHERIS_PROMOTION_BUDGET", "1")), 1, 5),
        )
