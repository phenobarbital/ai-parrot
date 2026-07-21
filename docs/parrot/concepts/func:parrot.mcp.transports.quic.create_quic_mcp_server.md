---
type: Concept
title: create_quic_mcp_server()
id: func:parrot.mcp.transports.quic.create_quic_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create configuration for QUIC/HTTP3 MCP server.
---

# create_quic_mcp_server

```python
def create_quic_mcp_server(name: str, host: str, port: int=4433, *, cert_path: Optional[str]=None, ca_cert_path: Optional[str]=None, insecure: bool=False, serialization: str='msgpack', enable_0rtt: bool=True, session_ticket_path: Optional[str]=None, **kwargs) -> MCPServerConfig
```

Create configuration for QUIC/HTTP3 MCP server.

This transport provides:
- ~40% lower latency than HTTP/SSE (0-RTT connection)
- ~60% smaller messages (MessagePack serialization)
- True multiplexing without head-of-line blocking
- Connection migration for mobile agents

Args:
    name: Server name for tool prefixing
    host: Server hostname
    port: Server port (default 4433, standard QUIC port)
    cert_path: Path to TLS certificate
    ca_cert_path: Path to CA certificate for verification
    insecure: Skip certificate verification (dev only!)
    serialization: "json", "msgpack", or "protobuf"
    enable_0rtt: Enable 0-RTT fast reconnection
    session_ticket_path: Path to store session tickets for 0-RTT
    
Returns:
    MCPServerConfig configured for QUIC transport
    
Example:
    >>> # Production setup
    >>> config = create_quic_mcp_server(
    ...     "ml-inference",
    ...     host="ml-cluster.internal.example.com",
    ...     port=4433,
    ...     ca_cert_path="/etc/ssl/ca-bundle.crt",
    ...     serialization="msgpack",
    ... )
    >>> 
    >>> # Development with self-signed cert
    >>> config = create_quic_mcp_server(
    ...     "local-tools",
    ...     host="localhost",
    ...     port=4433,
    ...     insecure=True,  # Only for development!
    ... )
    >>> 
    >>> await agent.add_mcp_server(config)
