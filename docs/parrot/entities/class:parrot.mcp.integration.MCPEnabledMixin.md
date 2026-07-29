---
type: Wiki Entity
title: MCPEnabledMixin
id: class:parrot.mcp.integration.MCPEnabledMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin to add complete MCP capabilities to agents.
---

# MCPEnabledMixin

Defined in [`parrot.mcp.integration`](../summaries/mod:parrot.mcp.integration.md).

```python
class MCPEnabledMixin
```

Mixin to add complete MCP capabilities to agents.

## Methods

- `async def add_mcp_server(self, config: MCPServerConfig) -> List[str]` — Add an MCP server with full feature support.
- `async def add_local_mcp_server(self, name: str, script_path: Union[str, Path], interpreter: str='python', **kwargs) -> List[str]` — Add a local stdio MCP server.
- `async def add_http_mcp_server(self, name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> List[str]` — Add an HTTP MCP server.
- `async def add_api_key_mcp_server(self, name: str, url: str, api_key: str, header_name: str='X-API-Key', **kwargs) -> List[str]` — Add an MCP server with API key auth.
- `async def add_oauth_mcp_server(self, name: str, url: str, user_id: str, oauth2: Optional[MCPOAuth2Config]=None, client_id: Optional[str]=None, auth_url: Optional[str]=None, token_url: Optional[str]=None, scopes: Optional[List[str]]=None, client_secret: Optional[str]=None, **kwargs) -> List[str]` — Add an MCP server with OAuth2 authorization code support.
- `async def add_perplexity_mcp_server(self, api_key: str, name: str='perplexity', **kwargs) -> List[str]` — Add a Perplexity MCP server capability.
- `async def add_fireflies_mcp_server(self, api_key: Optional[str]=None, **kwargs) -> List[str]` — Add Fireflies.ai MCP server capability.
- `async def add_chrome_devtools_mcp_server(self, browser_url: str='http://127.0.0.1:9222', name: str='chrome-devtools', **kwargs) -> List[str]` — Add Chrome DevTools MCP server capability.
- `async def add_google_maps_mcp_server(self, name: str='google-maps', **kwargs) -> List[str]` — Add Google Maps MCP server capability.
- `async def add_quic_mcp_server(self, name: str, host: str, port: int, cert_path: Optional[str]=None, **kwargs) -> List[str]` — Add a QUIC/HTTP3 MCP server connection.
- `async def add_websocket_mcp_server(self, name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> List[str]` — Add a WebSocket MCP server connection.
- `async def remove_mcp_server(self, server_name: str)`
- `async def reconfigure_mcp_server(self, config: MCPServerConfig) -> List[str]` — Reconfigure an existing MCP server with new configuration.
- `async def reconfigure_fireflies_mcp_server(self, api_key: str, **kwargs) -> List[str]` — Reconfigure Fireflies MCP server with a new API key.
- `async def reconfigure_perplexity_mcp_server(self, api_key: str, name: str='perplexity', **kwargs) -> List[str]` — Reconfigure Perplexity MCP server with a new API key.
- `def list_mcp_servers(self) -> List[str]`
- `def get_openai_mcp_tools(self, server_names: Optional[List[str]]=None) -> List[Dict[str, Any]]` — Get OpenAI-compatible MCP definitions for registered servers.
- `async def add_alphavantage_mcp_server(self, api_key: Optional[str]=None, name: str='alphavantage', **kwargs) -> List[str]` — Add AlphaVantage MCP server capability.
- `async def add_netsuite_mcp_server(self, account_id: str, client_id: str, user_id: str, **kwargs) -> List[str]` — Add NetSuite MCP server capability via OAuth2 Authorization Code + PKCE.
- `async def add_netsuite_m2m_mcp_server(self, account_id: str, client_id: str, certificate_id: str, private_key_path: str, **kwargs) -> List[str]` — Add NetSuite MCP server via OAuth2 Client Credentials (M2M) with certificate.
- `async def add_genmedia_mcp_servers(self, **kwargs) -> Dict[str, List[str]]` — Add all Google GenMedia MCP servers.
- `async def setup_mcp_servers(self, configurations: List[MCPServerConfig]) -> None` — Setup multiple MCP servers during initialization.
- `async def shutdown(self, **kwargs)`
