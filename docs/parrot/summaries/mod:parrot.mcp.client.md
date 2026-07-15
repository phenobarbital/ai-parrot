---
type: Wiki Summary
title: parrot.mcp.client
id: mod:parrot.mcp.client
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.mcp.client
relates_to:
- concept: class:parrot.mcp.client.AuthCredential
  rel: defines
- concept: class:parrot.mcp.client.AuthScheme
  rel: defines
- concept: class:parrot.mcp.client.MCPAuthHandler
  rel: defines
- concept: class:parrot.mcp.client.MCPClientConfig
  rel: defines
- concept: class:parrot.mcp.client.MCPConnectionError
  rel: defines
- concept: class:parrot.mcp.client.MCPRateLimitError
  rel: defines
- concept: func:parrot.mcp.client.parse_retry_after
  rel: defines
- concept: func:parrot.mcp.client.raise_for_jsonrpc_error
  rel: defines
- concept: mod:parrot.mcp.context
  rel: references
- concept: mod:parrot.mcp.filtering
  rel: references
- concept: mod:parrot.mcp.oauth2_config
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.mcp.client`

## Classes

- **`AuthScheme(str, Enum)`** — Type-safe authentication schemes.
- **`AuthCredential(BaseModel)`** — Type-safe credential container with validation.
- **`MCPClientConfig`** — Complete configuration for external MCP server connection.
- **`MCPAuthHandler`** — Handles various authentication types for MCP servers.
- **`MCPConnectionError(Exception)`** — MCP connection related errors.
- **`MCPRateLimitError(MCPConnectionError)`** — Raised when an MCP server rejects a request with a rate-limit error.

## Functions

- `def parse_retry_after(value: Any, *, now: Optional[float]=None) -> Optional[float]` — Normalize a server-provided retry hint into seconds-from-now.
- `def raise_for_jsonrpc_error(error: Dict[str, Any]) -> None` — Translate a JSON-RPC ``error`` object into the right exception.
