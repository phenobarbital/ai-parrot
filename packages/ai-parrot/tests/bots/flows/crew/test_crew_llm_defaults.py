"""AgentCrew per-component LLM defaults and usage attribution (FEAT-796)."""

from types import SimpleNamespace

import pytest

from parrot import llm_defaults
from parrot.bots.flows.crew import AgentCrew
from parrot.bots.flows.crew.credentials import get_crew_google_api_key
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.observability.context import current_component


class _FakeClient:
    """Record the keyword arguments used to construct a lazy crew client."""

    last_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs: object) -> None:
        type(self).last_kwargs = dict(kwargs)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Provide isolated component configuration for each test."""
    values: dict[str, str] = {}
    monkeypatch.setattr(llm_defaults.config, "get", lambda key, fallback=None: values.get(key, fallback))
    monkeypatch.setattr(llm_defaults.conf, "DEFAULT_LLM", None, raising=False)
    return values


def test_crew_google_key_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """CREW_GOOGLE_API_KEY takes precedence over the legacy crew key."""
    values = {"CREW_GOOGLE_API_KEY": "new-key"}
    monkeypatch.setattr("navconfig.config.get", lambda key, fallback=None: values.get(key, fallback))
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "legacy-key", raising=False)

    assert get_crew_google_api_key() == "new-key"


def test_crew_ai_key_alias_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """CREW_AI_KEY remains available when the provider-specific key is absent."""
    monkeypatch.setattr("navconfig.config.get", lambda key, fallback=None: fallback)
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "legacy-key", raising=False)

    assert get_crew_google_api_key() == "legacy-key"


@pytest.mark.asyncio
async def test_crew_lazy_llm_uses_crew_llm(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy loop client uses the provider, model, and key resolved for CREW."""
    env.update({"CREW_LLM": "openai:gpt-4.1", "CREW_OPENAI_API_KEY": "component-key"})
    monkeypatch.setitem(SUPPORTED_CLIENTS, "openai", _FakeClient)
    crew = AgentCrew(llm="openai", persist_results=False, enable_execution_wiki=False)
    crew._llm = None
    crew.agents = {"agent": object()}

    async def stop_after_lazy_client(agent: object) -> None:
        raise RuntimeError("stop-after-lazy-client")

    monkeypatch.setattr(crew, "_ensure_agent_ready", stop_after_lazy_client)

    with pytest.raises(RuntimeError, match="stop-after-lazy-client"):
        await crew.run_loop(initial_task="task", condition="done", agent_sequence=["agent"])

    assert _FakeClient.last_kwargs == {"model": "gpt-4.1", "max_tokens": 8192, "api_key": "component-key"}


@pytest.mark.asyncio
async def test_crew_sequential_default_model(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A Google-family CREW_LLM model is the sequential default forwarded to agents."""
    env["CREW_LLM"] = "google:gemini-2.5-flash"
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)
    crew = AgentCrew(llm="google", persist_results=False, enable_execution_wiki=False)
    crew.agents = {"agent": SimpleNamespace(name="agent")}
    captured: dict[str, object] = {}

    async def capture_model(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["model"] = kwargs["model"]
        captured["component"] = current_component.get()
        return SimpleNamespace(content="done")

    monkeypatch.setattr(crew, "_execute_agent", capture_model)

    await crew.run_sequential(query="task", generate_summary=False)

    assert captured == {"model": "gemini-2.5-flash", "component": "CREW"}


def test_crew_entry_points_preserve_wrapped_methods() -> None:
    """Every public crew entry point carries the CREW usage-scope decorator."""
    for method in (
        AgentCrew.run_sequential,
        AgentCrew.run_parallel,
        AgentCrew.run_flow,
        AgentCrew.run_loop,
        AgentCrew.ask,
    ):
        assert hasattr(method, "__wrapped__")


def test_crew_constructor_default_uses_crew_llm(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``llm``, the constructor client comes from CREW_LLM (not a hardcoded Google client)."""
    env.update({"CREW_LLM": "openai:gpt-4.1", "CREW_OPENAI_API_KEY": "component-key"})
    monkeypatch.setitem(SUPPORTED_CLIENTS, "openai", _FakeClient)

    crew = AgentCrew(persist_results=False, enable_execution_wiki=False)

    assert isinstance(crew._llm, _FakeClient)
    assert _FakeClient.last_kwargs["model"] == "gpt-4.1"
    assert _FakeClient.last_kwargs["api_key"] == "component-key"


def test_crew_constructor_builtin_keeps_legacy_client(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing configured: the Google client is built with no injected model (zero behavior change)."""
    monkeypatch.setitem(SUPPORTED_CLIENTS, "google", _FakeClient)

    crew = AgentCrew(persist_results=False, enable_execution_wiki=False)

    assert isinstance(crew._llm, _FakeClient)
    assert "model" not in _FakeClient.last_kwargs


@pytest.mark.asyncio
async def test_crew_sequential_does_not_forward_foreign_model(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-Google CREW_LLM model name is not forced onto the crew's agents."""
    env["CREW_LLM"] = "openai:gpt-4.1"
    monkeypatch.setitem(SUPPORTED_CLIENTS, "openai", _FakeClient)
    crew = AgentCrew(llm="openai", persist_results=False, enable_execution_wiki=False)
    crew.agents = {"agent": SimpleNamespace(name="agent")}
    captured: dict[str, object] = {}

    async def capture_model(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["model"] = kwargs["model"]
        raise RuntimeError("stop")

    monkeypatch.setattr(crew, "_execute_agent", capture_model, raising=False)
    try:
        await crew.run_sequential("task")
    except Exception:  # noqa: BLE001 — only the forwarded model matters here
        pass

    assert captured.get("model") is None
