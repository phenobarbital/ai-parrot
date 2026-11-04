"""AgentHandler per-component LLM defaults (FEAT-796, TASK-5142)."""

from types import SimpleNamespace
from typing import Any

import pytest

from parrot import conf, llm_defaults
from parrot.handlers.agents import abstract as handler_mod
from parrot.handlers.agents.abstract import AgentHandler
from parrot.observability.context import current_component


class _FakeConfig:
    def __init__(self, values: dict[str, str]):
        self._values = values

    def get(self, key: str, fallback: Any = None) -> Any:
        return self._values.get(key, fallback)


class _FakeAgent:
    created: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs
        _FakeAgent.created.append(kwargs)
        self.seen_component = None

    def set_response(self, response: Any) -> None:
        pass

    async def configure(self) -> None:
        pass

    async def ask(self, **kwargs: Any) -> str:
        self.seen_component = current_component.get()
        return "answer"


def _env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    monkeypatch.setattr(llm_defaults, "config", _FakeConfig(values))
    monkeypatch.setattr(conf, "DEFAULT_LLM", None, raising=False)


def _handler(cls: type = AgentHandler) -> AgentHandler:
    handler = cls.__new__(cls)
    handler._agent_class = _FakeAgent
    handler._agent_response = None
    handler._agent = None
    handler.logger = SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None)
    return handler


async def _create(handler: AgentHandler) -> _FakeAgent:
    return await handler._create_agent({})


async def test_handler_builtin_default(monkeypatch):
    _env(monkeypatch, {})
    agent = await _create(_handler())
    assert agent.kwargs["llm"] == "google"
    assert agent.kwargs["model"] == "gemini-2.5-pro"
    assert "llm_kwargs" not in agent.kwargs


async def test_handler_agent_llm_env(monkeypatch):
    _env(monkeypatch, {"AGENT_LLM": "openai:gpt-4o"})
    agent = await _create(_handler())
    assert agent.kwargs["llm"] == "openai"
    assert agent.kwargs["model"] == "gpt-4o"


async def test_handler_subclass_override_wins(monkeypatch):
    class Custom(AgentHandler):
        _use_llm = "google"
        _use_model = "gemini-2.5-flash"

    _env(monkeypatch, {"AGENT_LLM": "openai:gpt-4o"})
    agent = await _create(_handler(Custom))
    assert agent.kwargs["llm"] == "google"
    assert agent.kwargs["model"] == "gemini-2.5-flash"


async def test_handler_subclass_model_only(monkeypatch):
    class ModelOnly(AgentHandler):
        _use_model = "gemini-2.5-flash"

    _env(monkeypatch, {})
    agent = await _create(_handler(ModelOnly))
    assert agent.kwargs["llm"] == "google"
    assert agent.kwargs["model"] == "gemini-2.5-flash"


async def test_handler_api_key_passed(monkeypatch):
    _env(monkeypatch, {"AGENT_GOOGLE_API_KEY": "sekret-agent"})
    agent = await _create(_handler())
    assert agent.kwargs["llm_kwargs"] == {"api_key": "sekret-agent"}


async def test_ask_agent_tagged(monkeypatch):
    async def _tenant(app, request):
        return None

    monkeypatch.setattr(handler_mod, "resolve_request_tenant", _tenant)
    fake_request = SimpleNamespace(app={}, session={})

    class _ReqHandler(AgentHandler):
        request = fake_request

    handler = _handler(_ReqHandler)
    agent = _FakeAgent()
    handler._agent = agent
    handler._userid = "u1"

    # Response post-processing after agent.ask is out of scope; only the tag matters here.
    try:
        await handler.ask_agent(query="hi")
    except Exception:
        pass
    assert agent.seen_component == "AGENT"
    assert current_component.get() is None


async def test_handler_subclass_model_only_ignores_env_provider(monkeypatch):
    """A subclass owning the model never gets a foreign env provider paired with it."""

    class ModelOnly(AgentHandler):
        _use_model = "gemini-2.5-flash"

    _env(monkeypatch, {"AGENT_LLM": "anthropic:claude-sonnet-4"})
    agent = await _create(_handler(ModelOnly))
    assert agent.kwargs["llm"] == "google"
    assert agent.kwargs["model"] == "gemini-2.5-flash"


async def test_handler_subclass_provider_only_ignores_env_model(monkeypatch):
    class ProviderOnly(AgentHandler):
        _use_llm = "openai"

    _env(monkeypatch, {"AGENT_LLM": "anthropic:claude-sonnet-4"})
    agent = await _create(_handler(ProviderOnly))
    assert agent.kwargs["llm"] == "openai"
    assert "model" not in agent.kwargs
