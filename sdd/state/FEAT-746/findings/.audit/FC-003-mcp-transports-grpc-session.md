---
id: FC-003
query_id: [Q029, Q046]
type: read
intent: "MCP transports inventory: confirm stdio / http / unix / quic and the state of gRPC; read the transport base as the pattern for a new binary transport."
executed_at: 2026-10-25T22:43:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — MCP transports: stdio/http/streamable-http/sse/unix/websocket/quic shipped; a gRPC session exists but its protobuf import is commented out (JSON-RPC over gRPC, not a typed envelope)

## Summary

`ai-parrot-server` `parrot/mcp/transports/` contains `base.py, grpc_session.py, http.py, quic.py, sse.py, stdio.py, streamable_http.py, unix.py, websocket.py`. `MCPServerConfig` (server `mcp/config.py`) documents `transport` values `"stdio", "http", "streamable-http", "sse", "unix", "quic"` and carries `grpc_host/grpc_port/grpc_use_tls/grpc_cert_path/grpc_use_protobuf` plus `quic_serialization = "msgpack"` (QUIC already uses a binary serialization). `grpc_session.py` (162 lines) is a client-side `GrpcMCPSession` using `grpc.aio.Channel` with `# from .proto import mcp_pb2, mcp_pb2_grpc` commented out and `use_protobuf_messages: bool = False` — it tunnels JSON-RPC, so no protobuf-defined envelope exists. The QUIC transport is optional (`aioquic`) and lazy-loaded via core `parrot/mcp/_quic.py`. `RemoteMCPServerBase` (transports/base.py) is the server-side pattern: `register_tool(tool: AbstractTool)`, `register_resource`, and auth hooks (`_authenticate_api_key`, `_authenticate_bearer`, OAuth internal/external).

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/config.py`
  lines: 139
  symbol: `MCPServerConfig.transport` (comment)
  excerpt: |
    # "stdio", "http", "streamable-http", "sse", "unix" or "quic".
- path: `packages/ai-parrot-server/src/parrot/mcp/config.py`
  lines: 203-216
  symbol: `grpc_host`, `grpc_use_protobuf`, `quic_serialization`
  excerpt: |
    grpc_host: Optional[str] = None
    grpc_port: Optional[int] = None
    grpc_use_tls: bool = True
    grpc_use_protobuf: bool = False  # Use native protobuf vs JSON-RPC wrapper
    quic_serialization: str = "msgpack"  # "json" or "msgpack"
    quic_enable_0rtt: bool = True
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`
  lines: 1-17
  symbol: `GrpcMCPConfig`
  excerpt: |
    import grpc
    # from .proto import mcp_pb2, mcp_pb2_grpc
    @dataclass
    class GrpcMCPConfig:
        use_protobuf_messages: bool = False
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`
  lines: 19-32
  symbol: `GrpcMCPSession`
  excerpt: |
    class GrpcMCPSession:
        """MCP session for gRPC transport with optional protobuf messages."""
        def __init__(self, config: 'MCPServerConfig', logger):
            self._channel: Optional[grpc.aio.Channel] = None
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`
  lines: 83-150
  symbol: `GrpcMCPSession.send_request`, `list_tools`, `call_tool`, `disconnect`
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 19-27
  symbol: `RemoteMCPServerBase`
  excerpt: |
    class RemoteMCPServerBase(_CoreMCPServerBase):
        def __init__(self, config: MCPServerConfig):
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 64
  symbol: `RemoteMCPServerBase.register_tool`
  excerpt: |
    def register_tool(self, tool: AbstractTool):
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/base.py`
  lines: 174-274
  symbol: `_authenticate_request`, `_authenticate_api_key`, `_authenticate_bearer`
- path: `packages/ai-parrot/src/parrot/mcp/_quic.py`
  lines: 1-11
  symbol: `load_quic`
  excerpt: |
    """Lazy loader for the optional QUIC/WebTransport MCP transport.
    The QUIC transport is built on aioquic, which ships in the
- path: `packages/ai-parrot/src/parrot/mcp/registry.py`
  lines: 292-298
  symbol: transport registry entry `quic`
  excerpt: |
    name="quic",
    method_name="add_quic_mcp_server",

## Notes

Transport files listed via the Q036 tree (FC-016). The grpc_session is client-only and appears unfinished (no server counterpart found in the transports dir listing, no proto module). The brainstorm's VERIFY claim "no protobuf-defined envelope" holds; the claim "no gRPC transport" is only partly true — grpcio is reachable via the `navigator-eventbus[grpc]` extra and a JSON-RPC-over-gRPC session stub exists.
