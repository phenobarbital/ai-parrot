"""Tests for HumanTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.human.tool import HumanTool, HumanToolInput
from parrot.human.models import (
    InteractionResult,
    InteractionStatus,
    InteractionType,
)


class TestHumanToolInheritance:
    """Test that HumanTool follows AbstractTool conventions."""

    def test_inherits_from_abstract_tool(self):
        from parrot.tools.abstract import AbstractTool

        assert issubclass(HumanTool, AbstractTool)

    def test_has_correct_name(self):
        tool = HumanTool()
        assert tool.name == "ask_human"

    def test_has_description(self):
        tool = HumanTool()
        assert "human" in tool.description.lower()

    def test_has_args_schema(self):
        tool = HumanTool()
        assert tool.args_schema is HumanToolInput


class TestHumanToolInput:
    """Test the input schema."""

    def test_inherits_from_abstract_tool_args_schema(self):
        from parrot.tools.abstract import AbstractToolArgsSchema

        assert issubclass(HumanToolInput, AbstractToolArgsSchema)

    def test_schema_has_required_question(self):
        schema = HumanToolInput.model_json_schema()
        assert "question" in schema.get("required", [])

    def test_schema_has_interaction_type(self):
        schema = HumanToolInput.model_json_schema()
        assert "interaction_type" in schema["properties"]

    def test_schema_has_options(self):
        schema = HumanToolInput.model_json_schema()
        assert "options" in schema["properties"]


class TestHumanToolExecution:
    """Test _execute method."""

    @pytest.fixture
    def mock_manager(self):
        manager = MagicMock()
        manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.COMPLETED,
                consolidated_value="42",
            )
        )
        return manager

    @pytest.mark.asyncio
    async def test_execute_returns_consolidated_value(self, mock_manager):
        tool = HumanTool(
            manager=mock_manager,
            default_targets=["user1"],
        )
        result = await tool._execute(question="What is the answer?")
        assert result == "42"
        mock_manager.request_human_input.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_approval(self, mock_manager):
        mock_manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.COMPLETED,
                consolidated_value=True,
            )
        )
        tool = HumanTool(
            manager=mock_manager,
            default_targets=["user1"],
        )
        result = await tool._execute(
            question="Approve?",
            interaction_type="approval",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_execute_with_choices(self, mock_manager):
        mock_manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.COMPLETED,
                consolidated_value="opt_b",
            )
        )
        tool = HumanTool(
            manager=mock_manager,
            default_targets=["user1"],
        )
        result = await tool._execute(
            question="Pick one:",
            interaction_type="single_choice",
            options=[
                {"key": "opt_a", "label": "Option A"},
                {"key": "opt_b", "label": "Option B"},
            ],
        )
        assert result == "opt_b"

    @pytest.mark.asyncio
    async def test_execute_timeout_returns_message(self, mock_manager):
        mock_manager.request_human_input = AsyncMock(
            return_value=InteractionResult(
                interaction_id="test",
                status=InteractionStatus.TIMEOUT,
                timed_out=True,
            )
        )
        tool = HumanTool(
            manager=mock_manager,
            default_targets=["user1"],
        )
        result = await tool._execute(question="Hello?")
        assert "time limit" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_without_manager_returns_error(self):
        tool = HumanTool()
        result = await tool._execute(question="Hello?")
        assert "error" in result.lower()


class TestToolManagerIntegration:
    """Test that HumanTool works with ToolManager."""

    def test_registration_with_tool_manager(self):
        from parrot.tools.manager import ToolManager

        tool = HumanTool()
        manager = ToolManager()
        manager.register_tool(tool)

        assert "ask_human" in manager.list_tools()
        assert manager.get_tool("ask_human") is tool

    def test_tool_schema_generation(self):
        tool = HumanTool()
        schema = tool.get_tool_schema()

        assert schema is not None
        assert schema["name"] == "ask_human"
        assert "parameters" in schema
        assert "question" in schema["parameters"].get("properties", {})
