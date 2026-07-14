---
type: Wiki Entity
title: MCPToolManagerMixin
id: class:parrot.tools.mcp_mixin.MCPToolManagerMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin to add MCP capabilities to ToolManager.
---

# MCPToolManagerMixin

Defined in [`parrot.tools.mcp_mixin`](../summaries/mod:parrot.tools.mcp_mixin.md).

```python
class MCPToolManagerMixin
```

Mixin to add MCP capabilities to ToolManager.

This mixin adds the following capabilities:
- Connect to MCP servers (HTTP, SSE, WebSocket, stdio, QUIC)
- Register MCP tools as proxy tools in the ToolManager
- Generate OpenAI-compatible MCP definitions
- Manage server lifecycle (connect, disconnect, reconfigure)

Attributes:
    _mcp_clients: Dictionary mapping server names to MCPClient instances
    _mcp_configs: Dictionary mapping server names to MCPServerConfig
    _mcp_logger: Logger for MCP operations

## Methods

- `async def add_mcp_server(self, config: 'MCPServerConfig', context: Optional['ReadonlyContext']=None) -> List[str]` — Add MCP server with context-aware tool registration.
- `async def add_database_mcp(self, name: str, project_id: str, toolbox_path: str='./toolbox', database_type: str='bigquery', context: Optional['ReadonlyContext']=None, extra_env: Optional[Dict[str, str]]=None) -> List[str]` — Add a database MCP server using the genai-toolbox.
- `async def add_github_mcp(self, name: str='github', personal_access_token: Optional[str]=None, context: Optional['ReadonlyContext']=None, **kwargs) -> List[str]` — Add GitHub MCP server using npx.
- `async def add_github_remote_mcp(self, name: str='github-remote', personal_access_token: Optional[str]=None, toolsets: Union[List[str], str]='repos,issues', readonly: bool=True, lockdown: bool=False, context: Optional['ReadonlyContext']=None, **kwargs) -> List[str]` — Add GitHub Remote MCP server (insiders) via HTTP.
- `async def remove_mcp_server(self, server_name: str) -> bool` — Remove an MCP server and unregister its tools.
- `async def reconfigure_mcp_server(self, config: 'MCPServerConfig', context: Optional['ReadonlyContext']=None) -> List[str]` — Reconfigure an existing MCP server with new settings.
- `async def disconnect_all_mcp(self)` — Disconnect from all MCP servers and unregister their tools.
- `def list_mcp_servers(self) -> List[str]` — List all connected MCP server names.
- `def get_mcp_client(self, server_name: str) -> Optional['MCPClient']` — Get MCP client by server name.
- `def get_mcp_config(self, server_name: str) -> Optional['MCPServerConfig']` — Get MCP server configuration by name.
- `def get_openai_mcp_definitions(self, server_names: Optional[List[str]]=None) -> List[Dict[str, Any]]` — Get OpenAI-compatible MCP tool definitions.
- `def get_mcp_tools(self, server_name: Optional[str]=None) -> List[Any]` — Get all MCP tools, optionally filtered by server.
- `def has_mcp_servers(self) -> bool` — Check if any MCP servers are connected.
- `def get_mcp_server_info(self) -> Dict[str, Dict[str, Any]]` — Get detailed information about all connected MCP servers.
