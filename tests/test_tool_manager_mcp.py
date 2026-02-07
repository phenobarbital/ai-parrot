"""
Tests for ToolManager MCP integration.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.tools.manager import ToolManager
from parrot.mcp.client import MCPClientConfig as MCPServerConfig


@pytest.fixture
def tool_manager():
    """Create a fresh ToolManager instance."""
    return ToolManager(debug=True)


@pytest.fixture
def mock_mcp_config():
    """Create a mock MCP server config."""
    return MCPServerConfig(
        name="test-server",
        url="https://test-mcp.example.com/sse",
        transport="sse",
        description="A test MCP server",
        require_confirmation=False,
    )


@pytest.fixture
def mock_mcp_config_stdio():
    """Create a mock stdio MCP server config."""
    return MCPServerConfig(
        name="local-server",
        command="python",
        args=["mcp_server.py"],
        transport="stdio",
    )


class TestToolManagerMCPIntegration:
    """Test MCP capabilities integrated into ToolManager."""
    
    def test_mcp_attributes_initialized(self, tool_manager):
        """Test that MCP attributes are properly initialized."""
        assert hasattr(tool_manager, '_mcp_clients')
        assert hasattr(tool_manager, '_mcp_configs')
        assert isinstance(tool_manager._mcp_clients, dict)
        assert isinstance(tool_manager._mcp_configs, dict)
    
    def test_list_mcp_servers_empty(self, tool_manager):
        """Test listing MCP servers when none are connected."""
        servers = tool_manager.list_mcp_servers()
        assert servers == []
    
    def test_has_mcp_servers_false(self, tool_manager):
        """Test has_mcp_servers returns False when no servers."""
        assert tool_manager.has_mcp_servers() is False
    
    @pytest.mark.asyncio
    async def test_add_mcp_server(self, tool_manager, mock_mcp_config):
        """Test adding an MCP server."""
        mock_tools = [
            {
                'name': 'search',
                'description': 'Search the web',
                'inputSchema': {'type': 'object', 'properties': {}}
            },
            {
                'name': 'fetch',
                'description': 'Fetch a URL',
                'inputSchema': {'type': 'object', 'properties': {}}
            }
        ]
        
        with patch('parrot.mcp.integration.MCPClient') as MockClient:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_client.get_available_tools = AsyncMock(return_value=mock_tools)
            mock_client._is_tool_selected = MagicMock(return_value=True)
            mock_client._create_temp_tool_for_filtering = MagicMock()
            MockClient.return_value = mock_client
            
            registered = await tool_manager.add_mcp_server(mock_mcp_config)
            
            assert len(registered) == 2
            assert 'mcp_test-server_search' in registered
            assert 'mcp_test-server_fetch' in registered
            assert tool_manager.has_mcp_servers() is True
            assert 'test-server' in tool_manager.list_mcp_servers()
    
    @pytest.mark.asyncio
    async def test_remove_mcp_server(self, tool_manager, mock_mcp_config):
        """Test removing an MCP server."""
        # First add a server
        mock_tools = [
            {'name': 'tool1', 'description': 'Test', 'inputSchema': {}}
        ]
        
        with patch('parrot.mcp.integration.MCPClient') as MockClient:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_client.disconnect = AsyncMock()
            mock_client.get_available_tools = AsyncMock(return_value=mock_tools)
            mock_client._is_tool_selected = MagicMock(return_value=True)
            mock_client._create_temp_tool_for_filtering = MagicMock()
            MockClient.return_value = mock_client
            
            await tool_manager.add_mcp_server(mock_mcp_config)
            assert tool_manager.has_mcp_servers() is True
            
            # Now remove it
            result = await tool_manager.remove_mcp_server('test-server')
            
            assert result is True
            assert tool_manager.has_mcp_servers() is False
            assert 'test-server' not in tool_manager.list_mcp_servers()
    
    @pytest.mark.asyncio
    async def test_remove_nonexistent_server(self, tool_manager):
        """Test removing a server that doesn't exist."""
        result = await tool_manager.remove_mcp_server('nonexistent')
        assert result is False


class TestOpenAIMCPDefinitions:
    """Test OpenAI-compatible MCP definition generation."""
    
    @pytest.mark.asyncio
    async def test_get_openai_mcp_definitions(self, tool_manager, mock_mcp_config):
        """Test generating OpenAI-compatible MCP definitions."""
        # Manually add config (simulating a connected server)
        tool_manager._mcp_configs['test-server'] = mock_mcp_config
        tool_manager._mcp_clients['test-server'] = MagicMock()
        
        definitions = tool_manager.get_openai_mcp_definitions()
        
        assert len(definitions) == 1
        assert definitions[0]['type'] == 'mcp'
        assert definitions[0]['server_label'] == 'test-server'
        assert definitions[0]['server_url'] == 'https://test-mcp.example.com/sse'
        assert definitions[0]['require_approval'] == 'never'
        assert definitions[0]['server_description'] == 'A test MCP server'
    
    def test_skip_stdio_transport(self, tool_manager, mock_mcp_config_stdio):
        """Test that stdio transports are skipped for OpenAI definitions."""
        tool_manager._mcp_configs['local-server'] = mock_mcp_config_stdio
        tool_manager._mcp_clients['local-server'] = MagicMock()
        
        definitions = tool_manager.get_openai_mcp_definitions()
        
        # stdio transport should be skipped
        assert len(definitions) == 0
    
    def test_filter_by_server_names(self, tool_manager):
        """Test filtering definitions by server names."""
        config1 = MCPServerConfig(
            name="server1",
            url="https://server1.example.com/sse",
            transport="sse"
        )
        config2 = MCPServerConfig(
            name="server2",
            url="https://server2.example.com/sse",
            transport="sse"
        )
        
        tool_manager._mcp_configs['server1'] = config1
        tool_manager._mcp_configs['server2'] = config2
        tool_manager._mcp_clients['server1'] = MagicMock()
        tool_manager._mcp_clients['server2'] = MagicMock()
        
        # Get only server1
        definitions = tool_manager.get_openai_mcp_definitions(['server1'])
        
        assert len(definitions) == 1
        assert definitions[0]['server_label'] == 'server1'


class TestMCPToolFiltering:
    """Test MCP tool filtering functionality."""
    
    @pytest.mark.asyncio
    async def test_allowed_tools_filter(self, tool_manager):
        """Test that allowed_tools filter works."""
        config = MCPServerConfig(
            name="filtered-server",
            url="https://example.com/sse",
            transport="sse",
            allowed_tools=['search']  # Only allow 'search'
        )
        
        mock_tools = [
            {'name': 'search', 'description': 'Search', 'inputSchema': {}},
            {'name': 'fetch', 'description': 'Fetch', 'inputSchema': {}},
        ]
        
        with patch('parrot.mcp.integration.MCPClient') as MockClient:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_client.get_available_tools = AsyncMock(return_value=mock_tools)
            mock_client._is_tool_selected = MagicMock(return_value=True)
            mock_client._create_temp_tool_for_filtering = MagicMock()
            MockClient.return_value = mock_client
            
            registered = await tool_manager.add_mcp_server(config)
            
            # Only 'search' should be registered
            assert len(registered) == 1
            assert 'search' in registered[0]
    
    @pytest.mark.asyncio
    async def test_blocked_tools_filter(self, tool_manager):
        """Test that blocked_tools filter works."""
        config = MCPServerConfig(
            name="blocked-server",
            url="https://example.com/sse",
            transport="sse",
            blocked_tools=['dangerous_tool']
        )
        
        mock_tools = [
            {'name': 'safe_tool', 'description': 'Safe', 'inputSchema': {}},
            {'name': 'dangerous_tool', 'description': 'Dangerous', 'inputSchema': {}},
        ]
        
        with patch('parrot.mcp.integration.MCPClient') as MockClient:
            mock_client = AsyncMock()
            mock_client.connect = AsyncMock()
            mock_client.get_available_tools = AsyncMock(return_value=mock_tools)
            mock_client._is_tool_selected = MagicMock(return_value=True)
            mock_client._create_temp_tool_for_filtering = MagicMock()
            MockClient.return_value = mock_client
            
            registered = await tool_manager.add_mcp_server(config)
            
            # Only 'safe_tool' should be registered
            assert len(registered) == 1
            assert 'safe_tool' in registered[0]
