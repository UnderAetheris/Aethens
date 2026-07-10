from __future__ import annotations

import json
import logging
import re
from typing import Any

from .interface import ModelProvider, ModelRequest, ModelResponse, ResponseKind

logger = logging.getLogger(__name__)


def _build_prompt(request: ModelRequest) -> str:
    """Shared prompt builder for all real providers."""
    lines = [f"Task: {request.task}"]
    if request.context:
        lines.append(f"Context: {request.context}")
    if request.memory:
        lines.append(f"Memory: {'; '.join(request.memory)}")
    if request.kind is ResponseKind.PLAN_SUGGESTION:
        lines.append(f"Available tools: {', '.join(request.tool_names)}")
        lines.append(
            'Suggest a tool and arguments as JSON: {"tool": "name", "arg": {key: value}}'
        )
    return "\n".join(lines)


def _parse_suggestion(text: str, tool_names: tuple[str, ...]) -> dict[str, Any] | None:
    """Extract and validate a plan suggestion from model text output."""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        obj = json.loads(match.group())
        if isinstance(obj.get("tool"), str) and obj["tool"] in tool_names:
            return obj
    except Exception:
        pass
    return None


class MockProvider:
    """Deterministic floor: needs nothing, cannot fail."""

    name = "mock"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.kind is ResponseKind.CHAT:
            return ModelResponse(kind=request.kind, text=request.task, provider=self.name, ok=True)
        if request.kind is ResponseKind.SUMMARY:
            return ModelResponse(kind=request.kind, text=request.task[:200], provider=self.name, ok=True)
        # PLAN_SUGGESTION, KNOWLEDGE, SKILL_SUGGESTION: abstain so caller uses deterministic rules.
        return ModelResponse(kind=request.kind, suggestion=None, provider=self.name, ok=True)


class LocalProvider:
    """Talks to a local model server (Ollama-compatible); no cloud, no key."""

    name = "local"

    def __init__(self, endpoint: str, model: str, temperature: float = 0.2) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._temperature = temperature

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            import requests  # optional dep; raises ImportError -> FallbackProvider catches

            prompt = _build_prompt(request)
            resp = requests.post(
                f"{self._endpoint}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": self._temperature},
                },
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            suggestion = (
                _parse_suggestion(text, request.tool_names)
                if request.kind is ResponseKind.PLAN_SUGGESTION
                else None
            )
            return ModelResponse(
                kind=request.kind, text=text, suggestion=suggestion, provider=self.name, ok=True
            )
        except Exception as e:
            logger.debug("LocalProvider error: %r", e)
            raise


class ApiProvider:
    """Opt-in OpenAI-compatible API provider; key is env-gated and never logged."""

    name = "api"

    def __init__(self, base_url: str, model: str, api_key: str, temperature: float = 0.2) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._key = api_key  # held only here; never logged or stored elsewhere
        self._temperature = temperature

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            import requests

            prompt = _build_prompt(request)
            resp = requests.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self._temperature,
                },
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=30,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            suggestion = (
                _parse_suggestion(text, request.tool_names)
                if request.kind is ResponseKind.PLAN_SUGGESTION
                else None
            )
            return ModelResponse(
                kind=request.kind, text=text, suggestion=suggestion, provider=self.name, ok=True
            )
        except Exception as e:
            logger.debug("ApiProvider error: %r", e)
            raise


class FallbackProvider:
    """Try providers in order; the chain MUST end with MockProvider so complete() never raises."""

    name = "fallback"

    def __init__(self, chain: list[ModelProvider]) -> None:
        self._chain = chain

    def complete(self, request: ModelRequest) -> ModelResponse:
        last_err: Exception | None = None
        for provider in self._chain:
            try:
                resp = provider.complete(request)
                if resp.ok:
                    return resp
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug("Provider %s failed, falling through: %r", provider.name, e)

        # Unreachable when chain ends in MockProvider, but be defensive.
        return ModelResponse(
            kind=request.kind,
            ok=False,
            provider="none",
            text=f"all providers failed: {last_err!r}",
        )
