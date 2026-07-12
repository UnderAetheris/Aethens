from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Config:
    safe_mode: bool = True
    log_path: str = "aetheris_memory.jsonl"
    workspace_root: str = "."
    allowed_shell_commands: tuple[str, ...] = ("echo", "ls", "pwd", "cat")
    reflection_enabled: bool = True  # AETHERIS_REFLECTION=0 to disable
    code_loop_enabled: bool = False  # AETHERIS_CODE_LOOP=1 to enable workspace-aware repair
    # Default-on: flipped because the amplified benchmark passes its 5-clause
    # gate on its own merits.  Opt-out is always available (config or env).
    reasoning_enabled: bool = True  # AETHERIS_REASONING=off forces the v0 off-path
    # Experience Memory Engine v0: recording is a safe side-effect of the
    # executive's normal run (write path).  Consuming lessons is gated off by
    # default and benchmarked before it may steer anything.
    experience_record: bool = True    # AETHERIS_EXPERIENCE_RECORD=0 to disable writes
    experience_consume: bool = False   # AETHERIS_EXPERIENCE_CONSUME=1 to enable reads

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
            reasoning_enabled=os.getenv("AETHERIS_REASONING", "1") == "1",
            experience_record=os.getenv("AETHERIS_EXPERIENCE_RECORD", "1") != "0",
            experience_consume=os.getenv("AETHERIS_EXPERIENCE_CONSUME", "0") == "1",
        )


def resolve_reasoning_enabled(config: "Config", env: Mapping[str, str]) -> bool:
    """Resolve whether deliberative reasoning runs.

    Explicit precedence (off always wins on ambiguity):
      * AETHERIS_REASONING in {off,0,false}  -> force OFF (operator/debug opt-out)
      * AETHERIS_REASONING in {on,1,true}    -> force ON
      * unset / malformed                    -> fall back to config.reasoning_enabled

    A malformed env value is never treated as an implicit enable; it is ignored
    and the configured default (now True) stands.
    """
    raw = env.get("AETHERIS_REASONING")
    if raw is not None:
        val = raw.strip().lower()
        if val in ("off", "0", "false"):
            return False
        if val in ("on", "1", "true"):
            return True
        # malformed -> ignore env, defer to config (never silently force-on)
    return config.reasoning_enabled


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
