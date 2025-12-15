"""
Tests for A2A Remote Tools Integration.

These tests verify:
1. A2ARemoteAgentTool and A2ARemoteSkillTool inherit from AbstractTool
2. Tools can be registered with ToolManager
3. Tool execution works correctly via ToolManager
4. Schema generation works properly
5. Tool cloning works correctly
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional


class TestA2AToolInheritance:
    """Test that A2A tools properly inherit from AbstractTool."""

    def test_remote_agent_tool_inherits_from_abstract_tool(self):
        """Verify A2ARemoteAgentTool inherits from AbstractTool."""
        from parrot.tools.abstract import AbstractTool
        from parrot.a2a.client import A2ARemoteAgentTool

        assert issubclass(A2ARemoteAgentTool, AbstractTool)

    def test_remote_skill_tool_inherits_from_abstract_tool(self):
        """Verify A2ARemoteSkillTool inherits from AbstractTool."""
        from parrot.tools.abstract import AbstractTool
        from parrot.a2a.client import A2ARemoteSkillTool

        assert issubclass(A2ARemoteSkillTool, AbstractTool)

    def test_remote_agent_input_inherits_from_abstract_tool_args_schema(self):
        """Verify A2ARemoteAgentInput inherits from AbstractToolArgsSchema."""
        from parrot.tools.abstract import AbstractToolArgsSchema
        from parrot.a2a.client import A2ARemoteAgentInput

        assert issubclass(A2ARemoteAgentInput, AbstractToolArgsSchema)


class TestA2ARemoteAgentToolCreation:
    """Test A2ARemoteAgentTool creation and configuration."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock A2AClient with agent card."""
        client = MagicMock()
        client.agent_card = MagicMock()
        client.agent_card.name = "TestAgent"
        client.agent_card.description = "A test agent for unit testing"
        return client

    def test_tool_name_generation(self, mock_client):
        """Test that tool name is generated from agent name."""
        from parrot.a2a.client import A2ARemoteAgentTool

        tool = A2ARemoteAgentTool(mock_client)
        assert tool.name == "ask_testagent"

    def test_tool_custom_name(self, mock_client):
        """Test that custom tool name can be provided."""
        from parrot.a2a.client import A2ARemoteAgentTool

        tool = A2ARemoteAgentTool(mock_client, tool_name="my_custom_tool")
        assert tool.name == "my_custom_tool"

    def test_tool_description_generation(self, mock_client):
        """Test that description is generated from agent card."""
        from parrot.a2a.client import A2ARemoteAgentTool

        tool = A2ARemoteAgentTool(mock_client)
        assert "TestAgent" in tool.description
        assert mock_client.agent_card.description in tool.description

    def test_tool_has_args_schema(self, mock_client):
        """Test that tool has proper args_schema."""
        from parrot.a2a.client import A2ARemoteAgentTool, A2ARemoteAgentInput

        tool = A2ARemoteAgentTool(mock_client)
        assert tool.args_schema == A2ARemoteAgentInput

    def test_tool_has_tags(self, mock_client):
        """Test that tool has A2A-related tags."""
        from parrot.a2a.client import A2ARemoteAgentTool

        tool = A2ARemoteAgentTool(mock_client)
        assert "a2a" in tool.tags
        assert "remote-agent" in tool.tags


class TestA2ARemoteSkillToolCreation:
    """Test A2ARemoteSkillTool creation and configuration."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock A2AClient."""
        return MagicMock()

    @pytest.fixture
    def mock_skill(self):
        """Create a mock AgentSkill."""
        skill = MagicMock()
        skill.id = "test_skill"
        skill.name = "Test Skill"
        skill.description = "A test skill for unit testing"
        skill.tags = ["test", "example"]
        skill.input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "limit": {"type": "integer", "description": "Max results"}
            },
            "required": ["query"]
        }
        return skill

    def test_skill_tool_name_generation(self, mock_client, mock_skill):
        """Test that tool name is generated from skill ID."""
        from parrot.a2a.client import A2ARemoteSkillTool

        tool = A2ARemoteSkillTool(mock_client, mock_skill)
        assert tool.name == "remote_test_skill"

    def test_skill_tool_description(self, mock_client, mock_skill):
        """Test that tool uses skill description."""
        from parrot.a2a.client import A2ARemoteSkillTool

        tool = A2ARemoteSkillTool(mock_client, mock_skill)
        assert tool.description == mock_skill.description

    def test_skill_tool_has_dynamic_schema(self, mock_client, mock_skill):
        """Test that tool has dynamically generated schema."""
        from parrot.a2a.client import A2ARemoteSkillTool

        tool = A2ARemoteSkillTool(mock_client, mock_skill)
        assert tool.args_schema is not None

        # Check schema has expected fields
        schema = tool.args_schema.model_json_schema()
        assert "query" in schema.get("properties", {})
        assert "limit" in schema.get("properties", {})
        assert "context_id" in schema.get("properties", {})

    def test_skill_tool_tags_include_skill_tags(self, mock_client, mock_skill):
        """Test that tool includes skill's tags."""
        from parrot.a2a.client import A2ARemoteSkillTool

        tool = A2ARemoteSkillTool(mock_client, mock_skill)
        assert "a2a" in tool.tags
        assert "remote-skill" in tool.tags
        assert "test" in tool.tags
        assert "example" in tool.tags


class TestToolManagerIntegration:
    """Test A2A tools work with ToolManager."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock A2AClient."""
        client = MagicMock()
        client.agent_card = MagicMock()
        client.agent_card.name = "TestAgent"
        client.agent_card.description = "Test agent"
        return client

    def test_agent_tool_registration(self, mock_client):
        """Test that A2ARemoteAgentTool can be registered with ToolManager."""
        from parrot.a2a.client import A2ARemoteAgentTool
        from parrot.tools.manager import ToolManager

        tool = A2ARemoteAgentTool(mock_client)
        manager = ToolManager()

        manager.register_tool(tool)

        assert tool.name in manager.list_tools()
        assert manager.get_tool(tool.name) is tool

    def test_skill_tool_registration(self, mock_client):
        """Test that A2ARemoteSkillTool can be registered with ToolManager."""
        from parrot.a2a.client import A2ARemoteSkillTool
        from parrot.tools.manager import ToolManager

        skill = MagicMock()
        skill.id = "my_skill"
        skill.name = "My Skill"
        skill.description = "Test skill"
        skill.tags = []
        skill.input_schema = None

        tool = A2ARemoteSkillTool(mock_client, skill)
        manager = ToolManager()

        manager.register_tool(tool)

        assert tool.name in manager.list_tools()
        assert manager.get_tool(tool.name) is tool

    def test_get_tool_schema_works(self, mock_client):
        """Test that get_tool_schema works for A2A tools."""
        from parrot.a2a.client import A2ARemoteAgentTool

        tool = A2ARemoteAgentTool(mock_client)
        schema = tool.get_tool_schema()

        assert schema is not None
        assert schema["name"] == tool.name
        assert "parameters" in schema
        assert "question" in schema["parameters"].get("properties", {})


class TestToolExecution:
    """Test A2A tool execution via ToolManager."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock A2AClient with async methods."""
        from parrot.a2a.models import TaskState

        client = MagicMock()
        client.agent_card = MagicMock()
        client.agent_card.name = "TestAgent"
        client.agent_card.description = "Test agent"

        # Mock send_message to return a task with proper TaskState
        mock_task = MagicMock()
        mock_task.status.state = TaskState.COMPLETED  # Use actual enum
        mock_task.artifacts = [MagicMock()]
        mock_task.artifacts[0].parts = [MagicMock()]
        mock_task.artifacts[0].parts[0].text = "Test response from agent"

        client.send_message = AsyncMock(return_value=mock_task)

        return client

    @pytest.mark.asyncio
    async def test_execute_agent_tool_via_manager(self, mock_client):
        """Test executing A2ARemoteAgentTool via ToolManager.execute_tool."""
        from parrot.a2a.client import A2ARemoteAgentTool
        from parrot.tools.manager import ToolManager

        tool = A2ARemoteAgentTool(mock_client)
        manager = ToolManager()
        manager.register_tool(tool)

        # Mock the logger.notice method that navconfig provides but standard logging doesn't
        tool.logger.notice = MagicMock()

        # Execute via manager
        result = await manager.execute_tool(
            tool.name,
            {"question": "Hello, test!"}
        )

        assert result == "Test response from agent"
        mock_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skill_tool_via_manager(self, mock_client):
        """Test executing A2ARemoteSkillTool via ToolManager.execute_tool."""
        from parrot.a2a.client import A2ARemoteSkillTool
        from parrot.tools.manager import ToolManager

        skill = MagicMock()
        skill.id = "search"
        skill.name = "Search"
        skill.description = "Search for data"
        skill.tags = []
        skill.input_schema = {
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }

        mock_client.invoke_skill = AsyncMock(return_value={"results": ["item1"]})

        tool = A2ARemoteSkillTool(mock_client, skill)
        manager = ToolManager()
        manager.register_tool(tool)

        # Mock the logger.notice method that navconfig provides but standard logging doesn't
        tool.logger.notice = MagicMock()

        result = await manager.execute_tool(
            tool.name,
            {"query": "test query"}
        )

        assert result == {"results": ["item1"]}
        mock_client.invoke_skill.assert_called_once()



class TestToolCloning:
    """Test A2A tool cloning functionality."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock A2AClient."""
        client = MagicMock()
        client.agent_card = MagicMock()
        client.agent_card.name = "TestAgent"
        client.agent_card.description = "Test agent"
        return client

    def test_agent_tool_clone(self, mock_client):
        """Test that A2ARemoteAgentTool can be cloned."""
        from parrot.a2a.client import A2ARemoteAgentTool

        original = A2ARemoteAgentTool(
            mock_client,
            tool_name="my_tool",
            use_streaming=True
        )
        cloned = original.clone()

        assert cloned is not original
        assert cloned.name == original.name
        assert cloned.use_streaming == original.use_streaming
        assert cloned.client is original.client  # Shares client reference

    def test_skill_tool_clone(self, mock_client):
        """Test that A2ARemoteSkillTool can be cloned."""
        from parrot.a2a.client import A2ARemoteSkillTool

        skill = MagicMock()
        skill.id = "test"
        skill.name = "Test"
        skill.description = "Test skill"
        skill.tags = []
        skill.input_schema = None

        original = A2ARemoteSkillTool(mock_client, skill)
        cloned = original.clone()

        assert cloned is not original
        assert cloned.name == original.name
        assert cloned.skill is original.skill  # Shares skill reference
        assert cloned.client is original.client  # Shares client reference


class TestDynamicSchemaGeneration:
    """Test the _create_skill_input_model function."""

    def test_creates_model_with_context_id(self):
        """Test that generated model always has context_id field."""
        from parrot.a2a.client import _create_skill_input_model

        skill = MagicMock()
        skill.name = "Test"
        skill.input_schema = None

        Model = _create_skill_input_model(skill)
        schema = Model.model_json_schema()

        assert "context_id" in schema.get("properties", {})

    def test_creates_model_from_input_schema(self):
        """Test that model is created from skill's input_schema."""
        from parrot.a2a.client import _create_skill_input_model

        skill = MagicMock()
        skill.name = "Search"
        skill.input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results"},
                "include_metadata": {"type": "boolean", "description": "Include meta"}
            },
            "required": ["query"]
        }

        Model = _create_skill_input_model(skill)
        schema = Model.model_json_schema()
        props = schema.get("properties", {})

        assert "query" in props
        assert "max_results" in props
        assert "include_metadata" in props
        assert "context_id" in props  # Always present

    def test_required_fields_are_marked(self):
        """Test that required fields from input_schema are marked as required."""
        from parrot.a2a.client import _create_skill_input_model

        skill = MagicMock()
        skill.name = "Test"
        skill.input_schema = {
            "properties": {
                "required_field": {"type": "string", "description": "Required"},
                "optional_field": {"type": "string", "description": "Optional"}
            },
            "required": ["required_field"]
        }

        Model = _create_skill_input_model(skill)
        schema = Model.model_json_schema()

        assert "required_field" in schema.get("required", [])
