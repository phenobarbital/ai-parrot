"""Unit tests for parrot.bots.flows.core.types (TASK-913)."""
import pytest
from parrot.bots.flows.core.types import (
    AgentLike,
    AgentRef,
    DependencyResults,
    PromptBuilder,
    ActionCallback,
    FlowStatus,
)


class MockAgent:
    """Minimal object satisfying the AgentLike Protocol."""

    @property
    def name(self) -> str:
        return "mock"

    async def invoke(self, prompt: str, **kwargs):
        return f"response: {prompt}"


class BadAgent:
    """Object that does NOT satisfy AgentLike."""
    pass


class PartialAgent:
    """Has `name` but no `invoke` method."""

    @property
    def name(self) -> str:
        return "partial"


class TestAgentLikeProtocol:
    def test_conforming_object_is_instance(self):
        assert isinstance(MockAgent(), AgentLike)

    def test_non_conforming_object_is_not_instance(self):
        assert not isinstance(BadAgent(), AgentLike)

    def test_string_is_not_agent_like(self):
        assert not isinstance("agent-name", AgentLike)

    def test_partial_agent_not_instance(self):
        # Has name but no invoke — should NOT satisfy protocol
        assert not isinstance(PartialAgent(), AgentLike)


class TestFlowStatus:
    def test_values(self):
        assert FlowStatus.COMPLETED == "completed"
        assert FlowStatus.PARTIAL == "partial"
        assert FlowStatus.FAILED == "failed"

    def test_enum_has_exactly_three_members(self):
        assert len(FlowStatus) == 3

    def test_is_str_subclass(self):
        # FlowStatus inherits from str
        assert isinstance(FlowStatus.COMPLETED, str)

    def test_string_comparison(self):
        assert FlowStatus.COMPLETED == "completed"
        assert FlowStatus.FAILED != "completed"
