"""
MCP Tool Manager Mixin - Adds MCP server capabilities to ToolManager.

This mixin provides methods to:
- Add/remove MCP servers
- Register MCP tools as proxy tools
- Generate OpenAI-like MCP definitions for native injection
- Manage MCP server configurations

Usage:
    The mixin is automatically applied to ToolManager. Use it through
    any agent's tool_manager:
    
    ```python
    agent = BasicAgent(name="Demo", role="Assistant", goal="Test")
    await agent.tool_manager.add_mcp_server(config)
    ```
"""
import logging
from typing import Dict, List, Any, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from ..mcp.integration import MCPClient, MCPToolProxy
    from ..mcp.client import MCPClientConfig as MCPServerConfig
    from ..mcp.context import ReadonlyContext


class MCPToolManagerMixin:
    """Mixin to add MCP capabilities to ToolManager.
    
    This mixin adds the following capabilities:
    - Connect to MCP servers (HTTP, SSE, WebSocket, stdio, QUIC)
    - Register MCP tools as proxy tools in the ToolManager
    - Generate OpenAI-compatible MCP definitions
    - Manage server lifecycle (connect, disconnect, reconfigure)
    
    Attributes:
        _mcp_clients: Dictionary mapping server names to MCPClient instances
        _mcp_configs: Dictionary mapping server names to MCPServerConfig
        _mcp_logger: Logger for MCP operations
    """
    
    def _init_mcp(self):
        """Initialize MCP-related attributes.
        
        This should be called in ToolManager.__init__() to set up
        the MCP infrastructure.
        """
        self._mcp_clients: Dict[str, 'MCPClient'] = {}
        self._mcp_configs: Dict[str, 'MCPServerConfig'] = {}
        self._mcp_logger = logging.getLogger("ToolManager.MCP")
    
    async def add_mcp_server(
        self,
        config: 'MCPServerConfig',
        context: Optional['ReadonlyContext'] = None
    ) -> List[str]:
        """Add MCP server with context-aware tool registration.
        
        Connects to an MCP server and registers its tools as proxy tools
        in this ToolManager. The tools are filtered based on the config's
        allowed_tools, blocked_tools, and tool_filter settings.
        
        Args:
            config: MCPServerConfig with connection and filtering options
            context: Optional ReadonlyContext for dynamic filtering decisions
            
        Returns:
            List of registered tool names (prefixed with mcp_{server_name}_)
            
        Raises:
            MCPConnectionError: If connection to server fails
            
        Example:
            ```python
            config = MCPServerConfig(
                name="web-tools",
                url="https://mcp.example.com/sse",
                transport="sse",
                allowed_tools=["search", "fetch"]
            )
            tools = await tool_manager.add_mcp_server(config)
            # tools = ['mcp_web-tools_search', 'mcp_web-tools_fetch']
            ```
        """
        from ..mcp.integration import MCPClient, MCPToolProxy
        
        # Check if server with same name already exists
        if config.name in self._mcp_clients:
            self._mcp_logger.warning(
                f"MCP server '{config.name}' already exists. "
                "Use reconfigure_mcp_server() to update it."
            )
            return []
        
        client = MCPClient(config)
        
        try:
            await client.connect()
            self._mcp_clients[config.name] = client
            self._mcp_configs[config.name] = config
            
            available_tools = await client.get_available_tools()
            registered_tools = []
            
            for tool_def in available_tools:
                tool_name = tool_def.get('name', 'unknown')
                
                # Check basic allowed/blocked filters
                if self._should_skip_mcp_tool(tool_name, config):
                    continue
                
                # Apply dynamic filtering via MCPClient
                if not client._is_tool_selected(
                    client._create_temp_tool_for_filtering(tool_def),
                    context
                ):
                    self._mcp_logger.debug(f"Tool {tool_name} filtered out by predicate")
                    continue
                
                # Create proxy tool
                proxy_tool = MCPToolProxy(
                    mcp_tool_def=tool_def,
                    mcp_client=client,
                    server_name=config.name,
                    require_confirmation=getattr(config, 'require_confirmation', False),
                )
                
                # Register in self (ToolManager)
                self.register_tool(proxy_tool)
                registered_tools.append(proxy_tool.name)
                self._mcp_logger.info(f"Registered MCP tool: {proxy_tool.name}")
            
            transport_type = config.transport if config.transport != "auto" else "detected"
            
            self._mcp_logger.info(
                f"Successfully added MCP server {config.name} "
                f"({transport_type} transport) with {len(registered_tools)} tools"
            )
            return registered_tools
            
        except Exception as e:
            self._mcp_logger.error(f"Failed to add MCP server {config.name}: {e}")
            await self._cleanup_failed_mcp_client(config.name, client)
            raise
    
    def _should_skip_mcp_tool(self, tool_name: str, config: 'MCPServerConfig') -> bool:
        """Check if tool should be skipped based on basic filtering rules.
        
        Args:
            tool_name: Name of the tool to check
            config: Server configuration with filtering rules
            
        Returns:
            True if tool should be skipped, False otherwise
        """
        # Check allowed_tools whitelist
        if hasattr(config, 'allowed_tools') and config.allowed_tools:
            if tool_name not in config.allowed_tools:
                self._mcp_logger.debug(f"Tool {tool_name} not in allowed_tools, skipping")
                return True
        
        # Check blocked_tools blacklist
        if hasattr(config, 'blocked_tools') and config.blocked_tools:
            if tool_name in config.blocked_tools:
                self._mcp_logger.debug(f"Tool {tool_name} in blocked_tools, skipping")
                return True
        
        return False
    
    async def _cleanup_failed_mcp_client(self, name: str, client: 'MCPClient'):
        """Clean up a failed MCP client connection.
        
        Args:
            name: Server name
            client: MCPClient instance to clean up
        """
        try:
            await client.disconnect()
        except Exception as e:
            self._mcp_logger.debug(f"Error during cleanup disconnect: {e}")
        
        self._mcp_clients.pop(name, None)
        self._mcp_configs.pop(name, None)
    
    async def remove_mcp_server(self, server_name: str) -> bool:
        """Remove an MCP server and unregister its tools.
        
        Disconnects from the specified MCP server and removes all tools
        that were registered from it.
        
        Args:
            server_name: Name of the MCP server to remove
            
        Returns:
            True if server was removed, False if not found
            
        Example:
            ```python
            removed = await tool_manager.remove_mcp_server("web-tools")
            if removed:
                print("Server removed successfully")
            ```
        """
        if server_name not in self._mcp_clients:
            self._mcp_logger.warning(f"MCP server {server_name} not found")
            return False
        
        client = self._mcp_clients[server_name]
        
        # Find and remove all tools from this server
        # Iterate over copy of item keys since we're modifying the dictionary
        tool_names = list(self._tools.keys())
        tools_to_remove = []
        
        for name in tool_names:
            tool = self._tools[name]
            if hasattr(tool, 'server_name') and tool.server_name == server_name:
                tools_to_remove.append(name)
        
        for tool_name in tools_to_remove:
            self.unregister_tool(tool_name)
            self._mcp_logger.debug(f"Unregistered MCP tool: {tool_name}")
        
        # Disconnect client
        try:
            await client.disconnect()
        except Exception as e:
            self._mcp_logger.warning(f"Error disconnecting from {server_name}: {e}")
        
        # Clean up
        self._mcp_clients.pop(server_name, None)
        self._mcp_configs.pop(server_name, None)
        
        self._mcp_logger.info(
            f"Removed MCP server {server_name} and {len(tools_to_remove)} tools"
        )
        return True
    
    async def reconfigure_mcp_server(
        self,
        config: 'MCPServerConfig',
        context: Optional['ReadonlyContext'] = None
    ) -> List[str]:
        """Reconfigure an existing MCP server with new settings.
        
        This removes the existing server and re-adds it with new configuration.
        Useful for changing auth tokens, allowed tools, etc.
        
        Args:
            config: New MCPServerConfig (name must match existing server)
            context: Optional ReadonlyContext for filtering
            
        Returns:
            List of newly registered tool names
        """
        await self.remove_mcp_server(config.name)
        return await self.add_mcp_server(config, context)
    
    async def disconnect_all_mcp(self):
        """Disconnect from all MCP servers.
        
        Cleanly disconnects all MCP server connections. Tools are not
        automatically unregistered - call this during shutdown.
        """
        for name, client in list(self._mcp_clients.items()):
            try:
                await client.disconnect()
                self._mcp_logger.debug(f"Disconnected from {name}")
            except Exception as e:
                self._mcp_logger.warning(f"Error disconnecting from {name}: {e}")
        
        self._mcp_clients.clear()
        self._mcp_configs.clear()
    
    def list_mcp_servers(self) -> List[str]:
        """List all connected MCP server names.
        
        Returns:
            List of server names that are currently connected
        """
        return list(self._mcp_clients.keys())
    
    def get_mcp_client(self, server_name: str) -> Optional['MCPClient']:
        """Get MCP client by server name.
        
        Args:
            server_name: Name of the server
            
        Returns:
            MCPClient instance or None if not found
        """
        return self._mcp_clients.get(server_name)
    
    def get_mcp_config(self, server_name: str) -> Optional['MCPServerConfig']:
        """Get MCP server configuration by name.
        
        Args:
            server_name: Name of the server
            
        Returns:
            MCPServerConfig or None if not found
        """
        return self._mcp_configs.get(server_name)
    
    def get_openai_mcp_definitions(
        self,
        server_names: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible MCP tool definitions.
        
        Generates definitions in the format OpenAI accepts for native MCP
        server injection. Only servers with HTTP-based transports (http, sse,
        websocket) are included since OpenAI doesn't support stdio.
        
        The returned format is:
        ```python
        {
            "type": "mcp",
            "server_label": "server_name",
            "server_description": "...",  # optional
            "server_url": "https://...",
            "require_approval": "never" | "always",
            "allowed_tools": [...],  # optional
            "headers": {...}  # optional
        }
        ```
        
        Args:
            server_names: Optional list of server names to include.
                         If None, includes all HTTP-based servers.
                         
        Returns:
            List of OpenAI-compatible MCP definitions
            
        Example:
            ```python
            # Get all definitions
            tools = tool_manager.get_openai_mcp_definitions()
            
            # Get specific servers only
            tools = tool_manager.get_openai_mcp_definitions(['web-tools'])
            
            # Use with OpenAI
            from openai import OpenAI
            client = OpenAI()
            resp = client.responses.create(
                model="gpt-5",
                tools=tools,
                input="Search for AI news"
            )
            ```
        """
        definitions = []
        
        servers_to_include = server_names or list(self._mcp_configs.keys())
        
        for name in servers_to_include:
            config = self._mcp_configs.get(name)
            if not config:
                self._mcp_logger.debug(f"Server {name} not found, skipping")
                continue
            
            # Only HTTP-based transports work with OpenAI
            transport = getattr(config, 'transport', 'auto')
            if transport not in ("http", "sse", "websocket"):
                self._mcp_logger.debug(
                    f"Skipping {name}: transport '{transport}' not supported by OpenAI"
                )
                continue
            
            # Must have a URL
            url = getattr(config, 'url', None)
            if not url:
                self._mcp_logger.debug(f"Skipping {name}: no URL configured")
                continue
            
            # Build definition
            require_confirmation = getattr(config, 'require_confirmation', False)
            
            definition = {
                "type": "mcp",
                "server_label": name,
                "server_url": url,
                "require_approval": "always" if require_confirmation else "never",
            }
            
            # Add optional description
            description = getattr(config, 'description', None)
            if description:
                definition["server_description"] = description
            
            # Add optional allowed_tools
            allowed_tools = getattr(config, 'allowed_tools', None)
            if allowed_tools:
                definition["allowed_tools"] = allowed_tools
            
            # Add optional headers
            headers = getattr(config, 'headers', None)
            if headers:
                definition["headers"] = headers
            
            definitions.append(definition)
        
        return definitions
    
    def get_mcp_tools(self, server_name: Optional[str] = None) -> List[Any]:
        """Get all MCP tools, optionally filtered by server.
        
        Args:
            server_name: Optional server name to filter by.
                        If None, returns all MCP tools.
            
        Returns:
            List of MCPToolProxy instances
        """
        from ..mcp.integration import MCPToolProxy
        
        tools = []
        for tool in self._tools.values():
            if isinstance(tool, MCPToolProxy):
                if server_name is None or tool.server_name == server_name:
                    tools.append(tool)
        return tools
    
    def has_mcp_servers(self) -> bool:
        """Check if any MCP servers are connected.
        
        Returns:
            True if at least one MCP server is connected
        """
        return len(self._mcp_clients) > 0
    
    def get_mcp_server_info(self) -> Dict[str, Dict[str, Any]]:
        """Get detailed information about all connected MCP servers.
        
        Returns:
            Dictionary mapping server names to info dicts containing:
            - transport: Transport type (http, sse, stdio, etc.)
            - url: Server URL (if applicable)
            - tool_count: Number of tools registered from this server
            - connected: Whether client is connected
        """
        info = {}
        
        for name, config in self._mcp_configs.items():
            client = self._mcp_clients.get(name)
            tools = self.get_mcp_tools(name)
            
            info[name] = {
                "transport": getattr(config, 'transport', 'unknown'),
                "url": getattr(config, 'url', None),
                "tool_count": len(tools),
                "connected": client is not None and getattr(client, '_connected', False),
                "description": getattr(config, 'description', None),
            }
        
        return info
