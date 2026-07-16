---
type: Wiki Summary
title: parrot.mcp.integration
id: mod:parrot.mcp.integration
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.mcp.integration
relates_to:
- concept: class:parrot.mcp.integration.MCPClient
  rel: defines
- concept: class:parrot.mcp.integration.MCPEnabledMixin
  rel: defines
- concept: class:parrot.mcp.integration.MCPToolProxy
  rel: defines
- concept: class:parrot.mcp.integration.MCPValidationError
  rel: defines
- concept: func:parrot.mcp.integration.create_alphavantage_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_api_key_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_chrome_devtools_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_fireflies_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_google_maps_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_http_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_local_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_netsuite_m2m_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_netsuite_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_oauth_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_perplexity_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_quic_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_unix_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.create_websocket_mcp_server
  rel: defines
- concept: func:parrot.mcp.integration.validate_mcp_http
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.auth.oauth2.mcp_provider
  rel: references
- concept: mod:parrot.mcp.chrome
  rel: references
- concept: mod:parrot.mcp.client
  rel: references
- concept: mod:parrot.mcp.context
  rel: references
- concept: mod:parrot.mcp.filtering
  rel: references
- concept: mod:parrot.mcp.oauth
  rel: references
- concept: mod:parrot.mcp.oauth2_config
  rel: references
- concept: mod:parrot.mcp.transports.http
  rel: references
- concept: mod:parrot.mcp.transports.quic
  rel: references
- concept: mod:parrot.mcp.transports.sse
  rel: references
- concept: mod:parrot.mcp.transports.stdio
  rel: references
- concept: mod:parrot.mcp.transports.unix
  rel: references
- concept: mod:parrot.mcp.transports.websocket
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.mcp.integration`

## Classes

- **`MCPToolProxy(AbstractTool)`** — Proxy tool that wraps an individual MCP tool.
- **`MCPClient`** — Complete MCP client with stdio and HTTP transport support.
- **`MCPEnabledMixin`** — Mixin to add complete MCP capabilities to agents.
- **`MCPValidationError(Exception)`** — Raised when an MCP HTTP server fails the handshake validation check.

## Functions

- `def create_local_mcp_server(name: str, script_path: Union[str, Path], interpreter: str='python', **kwargs) -> MCPServerConfig` — Create configuration for local stdio MCP server.
- `def create_http_mcp_server(name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> MCPServerConfig` — Create configuration for HTTP MCP server.
- `def create_oauth_mcp_server(*, name: str, url: str, user_id: str, oauth2: Optional[MCPOAuth2Config]=None, client_id: Optional[str]=None, auth_url: Optional[str]=None, token_url: Optional[str]=None, scopes: Optional[list]=None, client_secret: Optional[str]=None, headers: Optional[dict]=None, **kwargs) -> MCPServerConfig` — Create an MCP server configuration with OAuth2 authorization code flow.
- `def create_netsuite_mcp_server(*, account_id: str, client_id: str, user_id: str, name: str='netsuite', headers: Optional[Dict[str, Any]]=None) -> MCPServerConfig` — Create a NetSuite MCP server configuration using OAuth2 Authorization Code + PKCE.
- `def create_netsuite_m2m_mcp_server(*, account_id: str, client_id: str, certificate_id: str, private_key_path: str, name: str='netsuite', token_store: Optional[TokenStore]=None, headers: Optional[Dict[str, Any]]=None) -> MCPServerConfig` — Create a NetSuite MCP server using OAuth2 Client Credentials (M2M) with certificate.
- `def create_unix_mcp_server(name: str, socket_path: str, **kwargs) -> MCPServerConfig` — Create a Unix socket MCP server configuration.
- `def create_websocket_mcp_server(name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> MCPServerConfig` — Create a WebSocket MCP server configuration.
- `def create_api_key_mcp_server(name: str, url: str, api_key: str, header_name: str='X-API-Key', use_bearer_prefix: bool=False, **kwargs) -> MCPServerConfig` — Create configuration for API key authenticated MCP server.
- `def create_fireflies_mcp_server(*, api_key: Optional[str]=None, api_base: str='https://api.fireflies.ai/mcp', **kwargs) -> MCPServerConfig` — Create configuration for Fireflies MCP server using stdio transport.
- `def create_chrome_devtools_mcp_server(browser_url: str='http://127.0.0.1:9222', name: str='chrome-devtools', **kwargs) -> MCPServerConfig` — Create configuration for Chrome DevTools MCP server.
- `def create_google_maps_mcp_server(name: str='google-maps', **kwargs) -> MCPServerConfig` — Create configuration for Google Maps MCP server.
- `def create_perplexity_mcp_server(api_key: str, *, name: str='perplexity', timeout_ms: int=600000, **kwargs) -> MCPServerConfig` — Create configuration for Perplexity MCP server.
- `def create_quic_mcp_server(name: str, host: str, port: int, cert_path: Optional[str]=None, serialization: str='msgpack', **kwargs) -> MCPServerConfig` — Create configuration for QUIC MCP server.
- `def create_alphavantage_mcp_server(api_key: Optional[str]=None, name: str='alphavantage', **kwargs) -> MCPServerConfig` — Create configuration for AlphaVantage MCP server.
- `async def validate_mcp_http(config: 'MCPServerConfig') -> None` — Validate that an MCP HTTP server is reachable and lists its tools.
