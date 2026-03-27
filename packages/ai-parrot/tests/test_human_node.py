"""Tests for HumanDecisionNode."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.human.node import HumanDecisionNode
from parrot.human.models import (
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
)


class TestHumanDecisionNodeCreation:
    """Test node creation and properties."""

    def test_name_property(self):
        node = HumanDecisionNode(name="gate", manager=MagicMock())
        assert node.name == "gate"

    def test_has_tool_manager_attribute(self):
        node = HumanDecisionNode(name="gate", manager=MagicMock())
        assert hasattr(node, "tool_manager")

    def test_can_create_without_config(self):
        node = HumanDecisionNode(name="gate", manager=MagicMock())
        assert node.interaction_config is None

    def test_can_create_with_interaction_config(self):
        config = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["u1"],
        )
        node = HumanDecisionNode(
            name="approval",
            manager=MagicMock(),
            interaction_config=config,
        )
        assert node.interaction_config.question == "Approve?"


class TestHumanDecisionNodeExecution:
    """Test the ask() method."""

    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock()
        manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.COMPLETED,
                consolidated_value=True,
            )
        )
        return manager

    @pytest.mark.asyncio
    async def test_ask_returns_consolidated_value(self, mock_manager):
        config = HumanInteraction(
            question="Continue?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["u1"],
        )
        node = HumanDecisionNode(
            name="gate",
            manager=mock_manager,
            interaction_config=config,
        )
        result = await node.ask(question="Previous findings...")
        assert result is True
        mock_manager.request_human_input.assert_called_once()

    @pytest.mark.asyncio
    async def test_ask_without_config_uses_question(self, mock_manager):
        mock_manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.COMPLETED,
                consolidated_value="go ahead",
            )
        )
        node = HumanDecisionNode(name="gate", manager=mock_manager)
        result = await node.ask(question="What should we do?")
        assert result == "go ahead"

        # Check the interaction was created with the question
        call_args = mock_manager.request_human_input.call_args
        interaction = call_args.args[0]
        assert "What should we do?" in interaction.question

    @pytest.mark.asyncio
    async def test_ask_timeout_returns_none(self, mock_manager):
        mock_manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.TIMEOUT,
                timed_out=True,
            )
        )
        config = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            target_humans=["u1"],
        )
        node = HumanDecisionNode(
            name="gate",
            manager=mock_manager,
            interaction_config=config,
        )
        result = await node.ask()
        assert result is None

    @pytest.mark.asyncio
    async def test_ask_without_manager_raises(self):
        node = HumanDecisionNode(name="gate", manager=None)
        with pytest.raises(RuntimeError, match="no manager"):
            await node.ask(question="test")


class TestFlowNodeCompatibility:
    """Test that HumanDecisionNode can be used as an agent in FlowNode."""

    def test_has_name_attribute(self):
        node = HumanDecisionNode(name="decision", manager=MagicMock())
        assert hasattr(node, "name")
        assert node.name == "decision"

    def test_has_ask_method(self):
        node = HumanDecisionNode(name="decision", manager=MagicMock())
        assert hasattr(node, "ask")
        assert callable(node.ask)

    def test_has_flow_node_compatible_interface(self):
        """Test that HumanDecisionNode has the interface FlowNode expects.

        FlowNode requires: .name (str), .ask() (coroutine), .tool_manager (attr).
        We validate the duck-type contract without importing the FSM module,
        which has deep transitive dependencies not available in the test env.
        """
        human_node = HumanDecisionNode(
            name="gate",
            manager=MagicMock(),
        )
        assert isinstance(human_node.name, str)
        assert asyncio.iscoroutinefunction(human_node.ask)
        assert hasattr(human_node, "tool_manager")
