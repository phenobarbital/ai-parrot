"""FEAT-882 — per-agent environment configuration in ``AbstractBot.configure``."""

from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

import pytest

from parrot import llm_defaults as ld
from parrot.bots.agent import BasicAgent
from parrot.clients import factory
from parrot.clients.base import AbstractClient, MessageResponse
from parrot.models import AIMessage, StructuredOutputConfig
from parrot.models.responses import InvokeResult


class _FakeClient:
    """Record constructor keyword arguments without reaching a provider."""

    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = dict(kwargs)


class _LiveClient(AbstractClient):
    """Minimal concrete client used only to exercise live-client precedence."""

    async def get_client(self) -> Any:
        """Return no provider client for this unit-test double."""
        return None

    async def ask(
        self,
        prompt: str,
        model: str,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[Any]] = None,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        use_tools: Optional[bool] = None,
        deep_research: bool = False,
        background: bool = False,
        lazy_loading: bool = False,
    ) -> MessageResponse:
        """Provide the required abstract method without making a request."""
        raise NotImplementedError

    async def ask_stream(
        self,
        prompt: str,
        model: str = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        files: Optional[List[Union[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        history: Optional[Sequence[Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        deep_research: bool = False,
        agent_config: Optional[Dict[str, Any]] = None,
        lazy_loading: bool = False,
    ) -> AsyncIterator[Union[str, AIMessage]]:
        """Provide the required abstract method without making a request."""
        raise NotImplementedError
        yield ""

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> MessageResponse:
        """Provide the required abstract method without making a request."""
        raise NotImplementedError

    async def invoke(
        self,
        prompt: str,
        *,
        output_type: Optional[type] = None,
        structured_output: Optional[StructuredOutputConfig] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        use_tools: bool = False,
        tools: Optional[list] = None,
    ) -> InvokeResult:
        """Provide the required abstract method without making a request."""
        raise NotImplementedError


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Layer hermetic FEAT-882 values over the active configuration."""
    values: dict[str, str] = {}
    real_get = ld.config.get
    monkeypatch.setattr(
        ld.config,
        "get",
        lambda key, *args, **kwargs: values[key] if key in values else real_get(key, *args, **kwargs),
    )
    monkeypatch.setattr(factory, "_DISCOVERED", True)
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "google", _FakeClient)
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "openai", _FakeClient)
    _FakeClient.last_kwargs = {}
    return values


def _agent(
    *, llm: Any = "google", llm_kwargs: Optional[dict[str, Any]] = None, name: str = "feat882-agent"
) -> BasicAgent:
    """Build an offline agent using the FEAT-882 default identity."""
    return BasicAgent(
        name=name,
        llm=llm,
        llm_kwargs=llm_kwargs or {},
        from_database=False,
        injection_detection=False,
    )


def test_configure_no_env_unchanged(env: dict[str, str]) -> None:
    """No FEAT-882 variables leave resolved configuration inputs unchanged."""
    agent = _agent(llm_kwargs={"custom": "value"})
    llm, model, kwargs = agent._apply_agent_env_overrides()

    assert llm == agent._llm_raw == "google"
    assert model is None
    assert kwargs == agent._llm_kwargs
    assert kwargs is not agent._llm_kwargs


def test_configure_env_model_overrides_declared_llm(env: dict[str, str]) -> None:
    """A provider:model environment override replaces the declared provider."""
    env["FEAT882_AGENT_MODEL"] = "openai:gpt-x"
    agent = _agent()

    llm, model, _ = agent._apply_agent_env_overrides()

    assert (llm, model, agent._llm_model) == ("openai:gpt-x", "gpt-x", "gpt-x")


def test_configure_env_model_bare_inherits_provider(env: dict[str, str]) -> None:
    """A bare model override retains the agent's declared provider."""
    env["FEAT882_AGENT_MODEL"] = "gemini-custom"
    agent = _agent()

    assert agent._apply_agent_env_overrides()[:2] == ("google:gemini-custom", "gemini-custom")


def test_configure_env_key_provider_follows_model(env: dict[str, str]) -> None:
    """The selected provider controls which per-agent API-key variable applies."""
    env["FEAT882_AGENT_MODEL"] = "openai:gpt-x"
    env["FEAT882_AGENT_OPENAI_API_KEY"] = "agent-openai-key"
    env["FEAT882_AGENT_GOOGLE_API_KEY"] = "agent-google-key"
    agent = _agent()

    assert agent._apply_agent_env_overrides()[2]["api_key"] == "agent-openai-key"


def test_configure_explicit_credential_beats_env_key(env: dict[str, str]) -> None:
    """An explicit credential has priority over a per-agent API key."""
    env["FEAT882_AGENT_GOOGLE_API_KEY"] = "agent-key"
    agent = _agent(llm_kwargs={"api_key": "explicit-key"})

    assert agent._apply_agent_env_overrides()[2]["api_key"] == "explicit-key"


def test_configure_component_default_key_replaced_by_env_key(env: dict[str, str]) -> None:
    """A component default is replaceable by a more-specific per-agent key."""
    env["CREW_GOOGLE_API_KEY"] = "crew-key"
    env["FEAT882_AGENT_GOOGLE_API_KEY"] = "agent-key"
    agent = _agent(llm_kwargs={"api_key": "crew-key"})

    assert agent._apply_agent_env_overrides()[2]["api_key"] == "agent-key"


def test_configure_client_instance_ignores_env(env: dict[str, str]) -> None:
    """A live client instance is never modified by environment overrides."""
    env["FEAT882_AGENT_MODEL"] = "openai:gpt-x"
    env["FEAT882_AGENT_OPENAI_API_KEY"] = "agent-key"
    client = object.__new__(_LiveClient)
    agent = _agent(llm=client)

    llm, model, kwargs = agent._apply_agent_env_overrides()

    assert llm is client
    assert model is None
    assert kwargs == agent._llm_kwargs


def test_configure_does_not_mutate_shared_llm_kwargs(env: dict[str, str]) -> None:
    """Per-agent key injection leaves the persisted kwargs mapping untouched."""
    env["FEAT882_AGENT_GOOGLE_API_KEY"] = "agent-key"
    shared = {"api_key": "crew-key"}
    env["CREW_GOOGLE_API_KEY"] = "crew-key"
    agent = _agent(llm_kwargs=shared)
    before = dict(agent._llm_kwargs)

    _, _, kwargs = agent._apply_agent_env_overrides()

    assert agent._llm_kwargs is shared
    assert agent._llm_kwargs == before
    assert kwargs["api_key"] == "agent-key"


def test_configure_reserved_name_warns_and_ignores(env: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    """Reserved component tokens do not consume component environment values."""
    env["CREW_MODEL"] = "openai:gpt-x"
    env["CREW_OPENAI_API_KEY"] = "secret-key"
    agent = _agent(name="crew")

    assert agent._apply_agent_env_overrides()[:2] == ("google", None)
    assert "reserved env prefix" in caplog.text
    assert "secret-key" not in caplog.text


def test_configure_malformed_env_model_raises(env: dict[str, str]) -> None:
    """Malformed model environment values identify their variable in the error."""
    env["FEAT882_AGENT_MODEL"] = "openai:"
    agent = _agent()

    with pytest.raises(ValueError, match="FEAT882_AGENT_MODEL"):
        agent._apply_agent_env_overrides()


@pytest.mark.asyncio
async def test_configure_passes_env_key_to_client(env: dict[str, str]) -> None:
    """Full configuration forwards the resolved per-agent key to the client."""
    env["FEAT882_AGENT_OPENAI_API_KEY"] = "agent-openai-key"
    agent = _agent(llm="openai")

    await agent.configure()

    assert _FakeClient.last_kwargs["api_key"] == "agent-openai-key"
