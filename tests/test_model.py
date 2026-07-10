import pytest

from aetheris.model import (
    FallbackProvider,
    ModelConfig,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    MockProvider,
    ResponseKind,
    build_provider,
)


def test_mock_provider_echoes_chat():
    mock = MockProvider()
    req = ModelRequest(kind=ResponseKind.CHAT, task="hello")
    resp = mock.complete(req)
    assert resp.ok
    assert resp.text == "hello"
    assert resp.provider == "mock"


def test_mock_provider_abstrains_on_plan_suggestion():
    mock = MockProvider()
    req = ModelRequest(kind=ResponseKind.PLAN_SUGGESTION, task="do x", tool_names=("echo",))
    resp = mock.complete(req)
    assert resp.ok
    assert resp.suggestion is None


def test_mock_provider_summarizes():
    mock = MockProvider()
    long_text = "x" * 300
    req = ModelRequest(kind=ResponseKind.SUMMARY, task=long_text)
    resp = mock.complete(req)
    assert resp.ok
    assert len(resp.text) <= 200


def test_fallback_falls_through_to_mock_on_failure():
    class Boom:
        name = "boom"

        def complete(self, req):
            raise RuntimeError("down")

    chain = [Boom(), MockProvider()]
    fb = FallbackProvider(chain)
    req = ModelRequest(kind=ResponseKind.CHAT, task="hi")
    resp = fb.complete(req)
    assert resp.ok
    assert resp.provider == "mock"
    assert resp.text == "hi"


def test_no_config_yields_mock_only():
    cfg = ModelConfig()
    prov = build_provider(cfg)
    assert prov.name == "mock"
    req = ModelRequest(kind=ResponseKind.PLAN_SUGGESTION, task="x", tool_names=("echo",))
    resp = prov.complete(req)
    assert resp.ok
    assert resp.suggestion is None


def test_config_from_env_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("AETHERIS_MODEL_PROVIDER", raising=False)
    cfg = ModelConfig.from_env()
    assert cfg.provider == "mock"
    prov = build_provider(cfg)
    resp = prov.complete(ModelRequest(kind=ResponseKind.CHAT, task="hi"))
    assert resp.ok


def test_fallback_provider_name():
    chain = [MockProvider()]
    fb = FallbackProvider(chain)
    assert fb.name == "fallback"


def test_model_request_frozen():
    req = ModelRequest(kind=ResponseKind.CHAT, task="hi")
    with pytest.raises(Exception):  # FrozenDataclassError or similar
        req.task = "bye"


def test_model_response_frozen():
    resp = ModelResponse(kind=ResponseKind.CHAT, text="hello")
    with pytest.raises(Exception):
        resp.text = "goodbye"
