from __future__ import annotations

import os
from dataclasses import dataclass

from .interface import ModelProvider
from .providers import ApiProvider, FallbackProvider, LocalProvider, MockProvider


@dataclass(frozen=True)
class ModelConfig:
    provider: str = "mock"
    model_name: str = ""
    local_endpoint: str = "http://127.0.0.1:11434"
    api_base_url: str = ""
    temperature: float = 0.2

    @classmethod
    def from_env(cls) -> ModelConfig:
        return cls(
            provider=os.getenv("AETHERIS_MODEL_PROVIDER", "mock"),
            model_name=os.getenv("AETHERIS_MODEL_NAME", ""),
            local_endpoint=os.getenv("AETHERIS_LOCAL_ENDPOINT", "http://127.0.0.1:11434"),
            api_base_url=os.getenv("AETHERIS_API_BASE_URL", ""),
            temperature=float(os.getenv("AETHERIS_MODEL_TEMPERATURE", "0.2")),
        )


def build_provider(cfg: ModelConfig) -> ModelProvider:
    """Assemble a fallback chain ending in MockProvider, per config.

    Chain order (first match wins):
      api    -> ApiProvider -> LocalProvider (if model_name set) -> MockProvider
      local  -> LocalProvider (if model_name set) -> MockProvider
      mock   -> MockProvider only
    """
    chain: list[ModelProvider] = []

    if cfg.provider == "api":
        key = os.getenv("AETHERIS_API_KEY", "")
        if key and cfg.api_base_url:
            chain.append(ApiProvider(cfg.api_base_url, cfg.model_name, key, cfg.temperature))

    if cfg.provider in ("api", "local") and cfg.model_name:
        chain.append(LocalProvider(cfg.local_endpoint, cfg.model_name, cfg.temperature))

    chain.append(MockProvider())

    if len(chain) == 1:
        return chain[0]  # mock-only: no FallbackProvider overhead
    return FallbackProvider(chain)
