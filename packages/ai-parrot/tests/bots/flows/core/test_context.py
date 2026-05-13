"""Unit tests for FlowContext.resolve_agent + AgentNotFoundError — FEAT-163.

Tests verify:
- FlowContext gains agent_registry attribute (optional, default None).
- resolve_agent(str) resolves via registry when registry is bound.
- resolve_agent(str) raises AgentNotFoundError when agent not found.
- resolve_agent(str) raises AgentNotFoundError when registry is None.
- resolve_agent(AgentLike) returns the object unchanged (passthrough).
- AgentNotFoundError is importable and inherits from LookupError.
"""
import pytest

from parrot.bots.flows.core.context import AgentNotFoundError, FlowContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubAgent:
    """Minimal AgentLike stub for testing."""

    @property
    def name(self) -> str:
        return "stub"

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return prompt

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return question


class StubRegistry:
    """Minimal AgentRegistry stub.

    Uses get_bot_instance() to match the real AgentRegistry.get_bot_instance()
    method (verified at implementation time via grep).
    """

    def __init__(self, agents: dict) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> object:
        return self._agents.get(name)


# ---------------------------------------------------------------------------
# AgentNotFoundError
# ---------------------------------------------------------------------------


class TestAgentNotFoundError:
    def test_is_lookup_error(self) -> None:
        assert issubclass(AgentNotFoundError, LookupError)

    def test_can_raise_and_catch(self) -> None:
        with pytest.raises(AgentNotFoundError):
            raise AgentNotFoundError("test error")

    def test_caught_as_lookup_error(self) -> None:
        with pytest.raises(LookupError):
            raise AgentNotFoundError("test error")


# ---------------------------------------------------------------------------
# FlowContext.agent_registry
# ---------------------------------------------------------------------------


class TestFlowContextAgentRegistry:
    def test_default_is_none(self) -> None:
        ctx = FlowContext(initial_task="test")
        assert ctx.agent_registry is None

    def test_can_set_registry(self) -> None:
        registry = StubRegistry({"stub": StubAgent()})
        ctx = FlowContext(initial_task="test", agent_registry=registry)
        assert ctx.agent_registry is registry


# ---------------------------------------------------------------------------
# FlowContext.resolve_agent
# ---------------------------------------------------------------------------


class TestResolveAgent:
    def test_returns_agent_for_known_ref(self) -> None:
        agent = StubAgent()
        ctx = FlowContext(
            initial_task="test",
            agent_registry=StubRegistry({"stub": agent}),
        )
        resolved = ctx.resolve_agent("stub")
        assert resolved is agent

    def test_raises_for_unknown_ref(self) -> None:
        ctx = FlowContext(
            initial_task="test",
            agent_registry=StubRegistry({}),
        )
        with pytest.raises(AgentNotFoundError):
            ctx.resolve_agent("missing")

    def test_raises_when_no_registry(self) -> None:
        ctx = FlowContext(initial_task="test")
        with pytest.raises(AgentNotFoundError, match="no agent_registry"):
            ctx.resolve_agent("anything")

    def test_passthrough_for_agentlike_instance(self) -> None:
        ctx = FlowContext(initial_task="test")
        agent = StubAgent()
        # Passing an AgentLike instance (not a string) returns it unchanged.
        result = ctx.resolve_agent(agent)
        assert result is agent

    def test_resolve_agent_error_message_contains_name(self) -> None:
        ctx = FlowContext(
            initial_task="test",
            agent_registry=StubRegistry({}),
        )
        with pytest.raises(AgentNotFoundError, match="missing-agent"):
            ctx.resolve_agent("missing-agent")
