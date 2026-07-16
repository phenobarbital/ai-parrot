---
type: Wiki Summary
title: parrot.mcp.transports.quic
id: mod:parrot.mcp.transports.quic
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: QUIC/HTTP3 MCP Server Implementation
relates_to:
- concept: class:parrot.mcp.transports.quic.MCPConnectionError
  rel: defines
- concept: class:parrot.mcp.transports.quic.MCPSerializer
  rel: defines
- concept: class:parrot.mcp.transports.quic.QuicMCPClientProtocol
  rel: defines
- concept: class:parrot.mcp.transports.quic.QuicMCPConfig
  rel: defines
- concept: class:parrot.mcp.transports.quic.QuicMCPServer
  rel: defines
- concept: class:parrot.mcp.transports.quic.QuicMCPServerProtocol
  rel: defines
- concept: class:parrot.mcp.transports.quic.QuicMCPSession
  rel: defines
- concept: class:parrot.mcp.transports.quic.SerializationFormat
  rel: defines
- concept: func:parrot.mcp.transports.quic.create_quic_mcp_server
  rel: defines
- concept: func:parrot.mcp.transports.quic.generate_self_signed_cert
  rel: defines
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.transports.base
  rel: references
---

# `parrot.mcp.transports.quic`

QUIC/HTTP3 MCP Server Implementation
====================================

High-performance MCP server using QUIC/HTTP3 with WebTransport support.
Provides ultra-low latency for distributed MCP deployments.

Features:
- 0-RTT connection establishment
- Multiplexed streams without head-of-line blocking
- Binary serialization (MessagePack) for efficiency
- Unreliable datagrams for telemetry
- Connection migration for mobile agents

Requires:
    pip install aioquic msgpack --break-system-packages

Usage:
    server = QuicMCPServer(config)
    server.register_tool(MyTool())
    await server.start()

# For development, create the certificate:
# openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

## Classes

- **`SerializationFormat(Enum)`** — Supported serialization formats for MCP messages.
- **`MCPConnectionError(Exception)`** — MCP connection error.
- **`QuicMCPConfig`** — Unified QUIC configuration.
- **`MCPSerializer`** — Handles serialization/deserialization of MCP messages.
- **`QuicMCPClientProtocol(QuicConnectionProtocol)`** — QUIC protocol handler for MCP client connections.
- **`QuicMCPServerProtocol(QuicConnectionProtocol)`** — QUIC protocol handler for MCP server connections.
- **`QuicMCPServer(MCPServerBase)`** — QUIC/HTTP3 MCP Server with WebTransport support.
- **`QuicMCPSession`** — MCP session over QUIC/HTTP3 with WebTransport.

## Functions

- `def create_quic_mcp_server(name: str, host: str, port: int=4433, *, cert_path: Optional[str]=None, ca_cert_path: Optional[str]=None, insecure: bool=False, serialization: str='msgpack', enable_0rtt: bool=True, session_ticket_path: Optional[str]=None, **kwargs) -> MCPServerConfig` — Create configuration for QUIC/HTTP3 MCP server.
- `def generate_self_signed_cert(cert_path: str='cert.pem', key_path: str='key.pem', hostname: str='localhost', days: int=365) -> None` — Generate self-signed certificate for development.
