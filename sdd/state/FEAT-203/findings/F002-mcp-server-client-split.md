---
id: F002
query: "parrot/mcp server vs client classification"
type: read
---

## Finding: parrot/mcp/ (14 files + 8 transport files)

### Server infrastructure (→ satellite):
- adapter.py — Tool-to-MCP adapter
- config.py — MCPServerConfig
- server.py — MCPServer factory (transport selection, CLI entry)
- cli.py — Click CLI for `parrot mcp serve`
- wrapper.py — Config loading (YAML/Python)
- chrome.py — Chrome process management
- resources.py — MCPResource data class
- transports/ (all 8): base.py, stdio.py, http.py, sse.py, unix.py, websocket.py, quic.py, grpc_session.py

### Client/consumer (→ stays in core):
- client.py — MCPClientConfig, AuthCredential, AuthScheme
- context.py — ReadonlyContext, MCPSessionManager
- filtering.py — Tool predicates and filters
- registry.py — MCPServerRegistry, MCPServerDescriptor (catalog of pre-built servers)

### Hybrid (needs splitting):
- integration.py — MCPClient + MCPToolProxy + MCPEnabledMixin (consumer) AND server factory
  functions (create_local_mcp_server, create_http_mcp_server, etc.)
- oauth.py — OAuthAuthorizationServer + OAuthRoutesMixin (server) AND OAuthManager +
  TokenStore impls (client). Also imports parrot.handlers.vault_utils.

### Also relevant: parrot/services/mcp/
- services/mcp/server.py — ParrotMCPServer (aiohttp-integrated MCP server)
- services/mcp/simple.py — SimpleMCPServer (standalone)
These are DIFFERENT from parrot/mcp/server.py. The CLI imports from services/mcp.
