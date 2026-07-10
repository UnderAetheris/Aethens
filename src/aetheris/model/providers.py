from __future__ import annotations

import json
import logging
from typing import Any

from .interface import ModelProvider, ModelRequest, ModelResponse, ResponseKind

logger = logging.getLogger(__name__)


class MockProvider:
    """Deterministic mock: needs nothing, cannot fail."""

    name = "mock"

    def complete(self, request: ModelRequest) -> ModelResponse:
        if request.kind is ResponseKind.CHAT:
            return ModelResponse(kind=request.kind, text=request.task, provider=self.name, ok=True)
        if request.kind is ResponseKind.SUMMARY:
            return ModelResponse(kind=request.kind, text=request.task[:200], provider=self.name, ok=True)
        # For plan suggestions and others, abstain (suggestion=None)
        return ModelResponse(kind=request.kind, suggestion=None, provider=self.name, ok=True)


class LocalProvider:
    """Talks to a local model server; no cloud, no key."""

    name = "local"

    def __init__(self, endpoint: str, model: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._model = model

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            import requests

            # Build a prompt from the request
            prompt = self._build_prompt(request)

            # POST to local endpoint (e.g., Ollama-compatible)
            resp = requests.post(
                f"{self._endpoint}/api/generate",
                json={"model": self._model, "prompt": prompt, "stream": False},
                timeout=30,
            )
            resp.raise_for_status()

            data = resp.json()
            text = data.get("response", "").strip()

            # For plan suggestions, try to parse structured output
            suggestion = None
            if request.kind is ResponseKind.PLAN_SUGGESTION:
                suggestion = self._parse_suggestion(text, request.tool_names)

            return ModelResponse(
                kind=request.kind, text=text, suggestion=suggestion, provider=self.name, ok=True
            )
        except Exception as e:
            logger.debug(f"LocalProvider error: {e!r}")
            raise

    def _build_prompt(self, request: ModelRequest) -> str:
        lines = [f"Task: {request.task}"]
        if request.context:
            lines.append(f"Context: {request.context}")
        if request.memory:
            lines.append(f"Memory: {'; '.join(request.memory)}")
        if request.kind is ResponseKind.PLAN_SUGGESTION:
            lines.append(f"Available tools: {', '.join(request.tool_names)}")
            lines.append(
                "Suggest a tool and arguments as JSON: {\"tool\": \"name\", \"arg\": {key: value}}"
            )
        return "\n".join(lines)

    def _parse_suggestion(self, text: str, tool_names: tuple[str, ...]) -> dict[str, Any] | None:
        try:
            # Try to extract JSON from the text
            import re

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            obj = json.loads(match.group())
            if isinstance(obj.get("tool"), str) and obj["tool"] in tool_names:
                return obj
        except Exception:
            pass
        return None


class ApiProvider:
    """Opt-in API model; env-gated key."""

    name = "api"

    def __init__(self, base_url: str, model: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._key = api_key  # held only here; never logged

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            import requests

            prompt = self._build_prompt(request)

            # Example: OpenAI-compatible API
            resp = requests.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                },
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=30,
            )
            resp.raise_for_status()

            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()

            suggestion = None
            if request.kind is ResponseKind.PLAN_SUGGESTION:
                suggestion = self._parse_suggestion(text, request.tool_names)

            return ModelResponse(
                kind=request.kind, text=text, suggestion=suggestion, provider=self.name, ok=True
            )
        except Exception as e:
            logger.debug(f"ApiProvider error: {e!r}")
            raise

    def _build_prompt(self, request: ModelRequest) -> str:
        lines = [f"Task: {request.task}"]
        if request.context:
            lines.append(f"Context: {request.context}")
        if request.memory:
            lines.append(f"Memory: {'; '.join(request.memory)}")
        if request.kind is ResponseKind.PLAN_SUGGESTION:
            lines.append(f"Available tools: {', '.join(request.tool_names)}")
            lines.append(
                "Suggest a tool and arguments as JSON: {\"tool\": \"name\", \"arg\": {key: value}}"
            )
        return "\n".join(lines)

    def _parse_suggestion(self, text: str, tool_names: tuple[str, ...]) -> dict[str, Any] | None:
        try:
            import re

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                return None
            obj = json.loads(match.group())
            if isinstance(obj.get("tool"), str) and obj["tool"] in tool_names:
                return obj
        except Exception:
            pass
        return None


class FallbackProvider:
    """Try providers in order; end at MockProvider (which never fails)."""

    name = "fallback"

    def __init__(self, chain: list[ModelProvider]) -> None:
        self._chain = chain

    def complete(self, request: ModelRequest) -> ModelResponse:
        last_err = None
        for provider in self._chain:
            try:
                resp = provider.complete(request)
                if resp.ok:
                    return resp
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.debug(f"Provider {provider.name} failed, falling through: {e!r}")
                continue

        # Should be unreachable if chain ends in MockProvider, but be defensive
        return ModelResponse(
            kind=request.kind,
            ok=False,
            provider="none",
            text=f"all providers failed: {last_err!r}",
        )
