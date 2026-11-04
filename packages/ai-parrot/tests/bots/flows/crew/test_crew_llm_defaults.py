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
    """The sequential model default is resolved from CREW_LLM before agent execution."""
    env["CREW_LLM"] = "openai:gpt-4.1"
    monkeypatch.setitem(SUPPORTED_CLIENTS, "openai", _FakeClient)
    crew = AgentCrew(llm="openai", persist_results=False, enable_execution_wiki=False)
    crew.agents = {"agent": SimpleNamespace(name="agent")}
    captured: dict[str, object] = {}

    async def capture_model(*args: object, **kwargs: object) -> SimpleNamespace:
        captured["model"] = kwargs["model"]
        captured["component"] = current_component.get()
        return SimpleNamespace(content="done")

    monkeypatch.setattr(crew, "_execute_agent", capture_model)

    await crew.run_sequential(query="task", generate_summary=False)

    assert captured == {"model": "gpt-4.1", "component": "CREW"}


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
