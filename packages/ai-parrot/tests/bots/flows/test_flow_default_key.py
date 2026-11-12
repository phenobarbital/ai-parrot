"""FEAT-882 — AgentsFlow FLOW_* defaults for unconfigured agents and the FLOW usage tag."""

import logging

import pytest

from parrot import llm_defaults as ld
from parrot.bots.flows.core.node import AgentNode
from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.flow import flow as flow_module
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.clients import factory
from parrot.observability.context import current_component, usage_component


class _StubAgent:
    """Constructed-but-unconfigured AbstractBot stand-in."""

    _default_llm = "google"

    def __init__(
        self,
        name: str,
        llm: str | None = None,
        llm_kwargs: dict[str, str] | None = None,
        configured: bool = False,
    ) -> None:
        self.name = name
        self._llm_raw = llm
        self._llm_model_explicit = False
        self._model_config: dict[str, object] = {}
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.is_configured = configured
        self.seen_components: list[str | None] = []

    async def invoke(self, prompt: str, **kwargs: object) -> str:
        """Return a fixed response while recording the usage component."""
        self.seen_components.append(current_component.get())
        return "ok"

    async def ask(self, question: str = "", **kwargs: object) -> object:
        """Return a fixed response while recording the usage component."""
        self.seen_components.append(current_component.get())
        return type("R", (), {"content": "ok"})()


class _Registry:
    """Minimal synchronous agent registry."""

    def __init__(self, agents: dict[str, _StubAgent]) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> _StubAgent | None:
        """Return the named agent when registered."""
        return self._agents.get(name)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Provide isolated component settings and supported providers."""
    values: dict[str, str] = {}
    monkeypatch.setattr(ld.config, "get", lambda key, fallback=None: values.get(key, fallback))
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", None, raising=False)
    monkeypatch.setattr(factory, "SUPPORTED_CLIENTS", {"google": object(), "openai": object()})
    monkeypatch.setattr(flow_module, "_flow_skip_logged", set())
    return values


def _agent_definition() -> FlowDefinition:
    """Build a definition containing one agent node."""
    return FlowDefinition(
        flow="defaults",
        nodes=[NodeDefinition(id="worker", type="agent", agent_ref="worker")],
        edges=[],
    )


def test_no_flow_settings_leave_agents_untouched(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """A global default alone must not re-point declarative or programmatic flow agents."""
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", "openai:global-model")
    declarative_agent = _StubAgent("worker")
    AgentsFlow.from_definition(_agent_definition(), agent_registry=_Registry({"worker": declarative_agent}))
    programmatic_agent = _StubAgent("programmatic")
    AgentsFlow("programmatic", persist_results=False).add_node(
        AgentNode(agent=programmatic_agent, node_id="programmatic")
    )

    assert declarative_agent._llm_raw is None
    assert declarative_agent._llm_kwargs == {}
    assert programmatic_agent._llm_raw is None
    assert programmatic_agent._llm_kwargs == {}


def test_flow_google_key_applies_to_every_agent_ingress(env: dict[str, str]) -> None:
    """Single nodes, decision voters, and programmatic nodes receive the FLOW Google key."""
    env["FLOW_GOOGLE_API_KEY"] = "flow-secret"
    original_kwargs = {"temperature": "0"}
    single = _StubAgent("worker", llm_kwargs=original_kwargs)
    AgentsFlow.from_definition(_agent_definition(), agent_registry=_Registry({"worker": single}))

    voter = _StubAgent("voter")
    decision = FlowDefinition(
        flow="decision-defaults",
        nodes=[
            NodeDefinition(
                id="vote",
                type="decision",
                config={
                    "mode": "ballot",
                    "decision_type": "binary",
                    "agent_refs": ["voter"],
                },
            )
        ],
        edges=[],
    )
    AgentsFlow.from_definition(decision, agent_registry=_Registry({"voter": voter}))

    programmatic = _StubAgent("programmatic")
    AgentsFlow("programmatic", persist_results=False).add_node(AgentNode(agent=programmatic, node_id="node"))

    assert single._llm_kwargs == {"temperature": "0", "api_key": "flow-secret"}
    assert single._llm_kwargs is not original_kwargs
    assert original_kwargs == {"temperature": "0"}
    assert voter._llm_kwargs == {"api_key": "flow-secret"}
    assert programmatic._llm_kwargs == {"api_key": "flow-secret"}


def test_flow_llm_sets_provider_before_injecting_key(env: dict[str, str]) -> None:
    """FLOW_LLM selects the provider used for component-key injection."""
    env.update({"FLOW_LLM": "openai:gpt-x", "FLOW_OPENAI_API_KEY": "openai-secret"})
    agent = _StubAgent("worker")

    AgentsFlow.from_definition(_agent_definition(), agent_registry=_Registry({"worker": agent}))

    assert agent._llm_raw == "openai:gpt-x"
    assert agent._llm_kwargs == {"api_key": "openai-secret"}


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("_llm_raw", "google:explicit"),
        ("_llm_model_explicit", True),
        ("_model_config", {"model": "explicit"}),
    ],
)
def test_flow_llm_does_not_override_explicit_agent_model(env: dict[str, str], attribute: str, value: object) -> None:
    """Any explicit agent model declaration blocks FLOW_LLM reassignment."""
    env["FLOW_LLM"] = "openai:gpt-x"
    agent = _StubAgent("worker")
    setattr(agent, attribute, value)

    flow_module._apply_flow_defaults(agent)

    assert agent._llm_raw != "openai:gpt-x"


def test_configured_agent_is_skipped_and_logged_once_per_name(
    env: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    """Configured agents remain unchanged and emit one key-free INFO record per name."""
    env.update({"FLOW_LLM": "openai:gpt-x", "FLOW_GOOGLE_API_KEY": "never-log-this"})
    agent = _StubAgent("configured", llm="google:existing", llm_kwargs={"api_key": "existing"}, configured=True)
    caplog.set_level(logging.INFO, logger=flow_module.logger.name)

    flow_module._apply_flow_defaults(agent)
    flow_module._apply_flow_defaults(agent)

    records = [record for record in caplog.records if "already configured" in record.getMessage()]
    assert len(records) == 1
    assert agent._llm_raw == "google:existing"
    assert agent._llm_kwargs == {"api_key": "existing"}
    assert "never-log-this" not in caplog.text
    assert "api_key" not in caplog.text


@pytest.mark.asyncio
async def test_run_flow_sets_and_restores_flow_usage_component(env: dict[str, str]) -> None:
    """Agent calls see FLOW while the caller's prior component is restored afterward."""
    agent = _StubAgent("worker")
    flow = AgentsFlow("usage", persist_results=False)
    flow.add_node(AgentNode(agent=agent, node_id="worker"))

    with usage_component("OUTER"):
        result = await flow.run_flow("prompt")
        assert current_component.get() == "OUTER"

    assert result.status == "completed"
    assert agent.seen_components == ["FLOW"]
    assert current_component.get() is None
