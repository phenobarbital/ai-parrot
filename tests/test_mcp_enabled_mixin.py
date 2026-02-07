"""
Tests for updated MCPEnabledMixin.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.mcp import MCPServerConfig
from parrot.mcp.integration import MCPEnabledMixin


# Create a dummy class that uses the mixin
class DummyAgent(MCPEnabledMixin):
    def __init__(self):
        self.tool_manager = MagicMock()
        super().__init__()


@pytest.fixture
def mock_agent():
    """Create a dummy agent with MCP capabilities."""
    return DummyAgent()


class TestMCPEnabledMixinIntegration:
    """Test MCPEnabledMixin uses tool_manager directly."""
    
    def test_no_separate_mcp_manager(self, mock_agent):
        """Test that agent doesn't have separate mcp_manager."""
        # The mcp_manager property should return tool_manager with a warning
        assert hasattr(mock_agent, 'tool_manager')
        assert mock_agent._mcp_initialized is True
        assert not hasattr(mock_agent, 'mcp_manager')
    
    @pytest.mark.asyncio
    async def test_add_mcp_server_uses_tool_manager(self, mock_agent):
        """Test that add_mcp_server delegates to tool_manager."""
        config = MCPServerConfig(
            name="test",
            url="https://test.com/sse",
            transport="sse"
        )
        
        # Mock the tool_manager's add_mcp_server
        mock_agent.tool_manager.add_mcp_server = AsyncMock(return_value=['mcp_test_tool1'])
        
        result = await mock_agent.add_mcp_server(config)
        
        mock_agent.tool_manager.add_mcp_server.assert_called_once_with(config)
        assert result == ['mcp_test_tool1']
    
    @pytest.mark.asyncio
    async def test_remove_mcp_server_uses_tool_manager(self, mock_agent):
        """Test that remove_mcp_server delegates to tool_manager."""
        mock_agent.tool_manager.remove_mcp_server = AsyncMock(return_value=True)
        
        await mock_agent.remove_mcp_server('test-server')
        
        mock_agent.tool_manager.remove_mcp_server.assert_called_once_with('test-server')
    
    def test_list_mcp_servers_uses_tool_manager(self, mock_agent):
        """Test that list_mcp_servers delegates to tool_manager."""
        mock_agent.tool_manager.list_mcp_servers = MagicMock(return_value=['server1', 'server2'])
        
        servers = mock_agent.list_mcp_servers()
        
        assert servers == ['server1', 'server2']
    
    def test_get_openai_mcp_tools(self, mock_agent):
        """Test getting OpenAI-compatible MCP definitions."""
        expected = [
            {
                'type': 'mcp',
                'server_label': 'test',
                'server_url': 'https://test.com/sse'
            }
        ]
        mock_agent.tool_manager.get_openai_mcp_definitions = MagicMock(return_value=expected)
        
        result = mock_agent.get_openai_mcp_tools()
        
        assert result == expected
    
    @pytest.mark.asyncio
    async def test_shutdown_disconnects_mcp(self, mock_agent):
        """Test that shutdown disconnects all MCP servers."""
        mock_agent.tool_manager.disconnect_all_mcp = AsyncMock()
        
        await mock_agent.shutdown()
        
        mock_agent.tool_manager.disconnect_all_mcp.assert_called_once()
