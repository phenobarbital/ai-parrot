---
type: Concept
title: create_quic_mcp_server()
id: func:parrot.mcp.integration.create_quic_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for QUIC MCP server.
---

# create_quic_mcp_server

```python
def create_quic_mcp_server(name: str, host: str, port: int, cert_path: Optional[str]=None, serialization: str='msgpack', **kwargs) -> MCPServerConfig
```

Create configuration for QUIC MCP server.

Args:
    name: Server name
    host: Server hostname
    port: Server port
    cert_path: Path to TLS certificate (optional for client if trusted)
    serialization: Serialization format ("msgpack" or "json")
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for QUIC transport
