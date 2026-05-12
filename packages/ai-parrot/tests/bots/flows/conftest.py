"""Shared pytest fixtures for parrot.bots.flows integration tests — FEAT-163.

Provides:
    stub_registry: Lightweight in-memory AgentRegistry stub with get_bot_instance.
    flow_context: A FlowContext wired to an empty stub registry.
"""
import pytest

from parrot.bots.flows.core.context import FlowContext


class StubRegistry:
    """Minimal AgentRegistry stub matching the real get_bot_instance interface."""

    def __init__(self) -> None:
        self._agents: dict = {}

    def register(self, agent: object) -> None:
        """Register an agent under its .name."""
        self._agents[agent.name] = agent  # type: ignore[attr-defined]

    def get_bot_instance(self, name: str) -> object:
        """Sync lookup — mirrors AgentRegistry.get_bot_instance."""
        return self._agents.get(name)


@pytest.fixture
def stub_registry() -> StubRegistry:
    """In-memory AgentRegistry stub for integration tests."""
    return StubRegistry()


@pytest.fixture
def flow_context(stub_registry: StubRegistry) -> FlowContext:
    """FlowContext wired to the stub registry."""
    return FlowContext(initial_task="integration test", agent_registry=stub_registry)
