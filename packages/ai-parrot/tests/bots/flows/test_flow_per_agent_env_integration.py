"""FEAT-882 — per-agent env key vs FLOW default through ``AgentsFlow``."""

import pytest

from parrot import llm_defaults as ld
from parrot.bots.agent import BasicAgent
from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.flow import flow as flow_module
from parrot.bots.flows.flow.definition import EdgeDefinition, FlowDefinition, NodeDefinition
from parrot.clients import factory

AGENT_NAME = "feat882-flow-agent"


class _FakeClient:
    """Record constructor keyword arguments instead of reaching a provider."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs) -> None:
        """Store the client configuration for assertions."""
        type(self).last_kwargs = dict(kwargs)


class _Registry:
    """Minimal synchronous registry used by ``AgentsFlow.from_definition``."""

    def __init__(self, agents: dict) -> None:
        """Store agents keyed by their registry name."""
        self._agents = agents

    def get_bot_instance(self, name: str):
        """Return the requested agent, or ``None`` when it is unknown."""
        return self._agents.get(name)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Provide hermetic feature settings while preserving unrelated config values."""
    values: dict[str, str] = {}
    real_get = ld.config.get
    monkeypatch.setattr(
        ld.config,
        "get",
        lambda key, *args, **kwargs: values[key] if key in values else real_get(key, *args, **kwargs),
    )
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "google", _FakeClient)
    monkeypatch.setattr(flow_module, "_flow_skip_logged", set())
    _FakeClient.last_kwargs = {}
    return values


def _definition() -> FlowDefinition:
    """Build a linear definition containing the feature test agent."""
    return FlowDefinition(
        flow="feat882-flow",
        nodes=[
            NodeDefinition(id="start", type="start"),
            NodeDefinition(id="agent", type="agent", agent_ref=AGENT_NAME),
        ],
        edges=[EdgeDefinition(**{"from": "start", "to": "agent", "condition": "always"})],
    )


async def test_flow_default_key_reaches_client(env: dict[str, str]) -> None:
    """An unconfigured flow agent receives the FLOW Google API key."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-key"
    agent = BasicAgent(name=AGENT_NAME, llm="google", from_database=False)

    AgentsFlow.from_definition(_definition(), agent_registry=_Registry({AGENT_NAME: agent}))
    await agent.configure()

    assert _FakeClient.last_kwargs["api_key"] == "flow-key"


async def test_per_agent_key_beats_flow_default(env: dict[str, str]) -> None:
    """The agent-specific key replaces the FLOW default during configuration."""
    env.update(
        {
            "FLOW_GOOGLE_API_KEY": "flow-key",
            "FEAT882_FLOW_AGENT_GOOGLE_API_KEY": "agent-key",
        }
    )
    agent = BasicAgent(name=AGENT_NAME, llm="google", from_database=False)

    AgentsFlow.from_definition(_definition(), agent_registry=_Registry({AGENT_NAME: agent}))
    await agent.configure()

    assert _FakeClient.last_kwargs["api_key"] == "agent-key"


async def test_configured_registry_agent_uses_per_agent_key(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """A configured agent keeps its per-agent key when FLOW defaults are skipped."""
    env.update(
        {
            "FLOW_GOOGLE_API_KEY": "flow-key",
            "FEAT882_FLOW_AGENT_GOOGLE_API_KEY": "agent-key",
        }
    )
    agent = BasicAgent(name=AGENT_NAME, llm="google", from_database=False)

    await agent.configure()
    caplog.set_level("INFO", logger=flow_module.logger.name)
    AgentsFlow.from_definition(_definition(), agent_registry=_Registry({AGENT_NAME: agent}))

    records = [record for record in caplog.records if "already configured" in record.getMessage()]
    assert _FakeClient.last_kwargs["api_key"] == "agent-key"
    assert "api_key" not in agent._llm_kwargs
    assert len(records) == 1
    assert "flow-key" not in caplog.text
