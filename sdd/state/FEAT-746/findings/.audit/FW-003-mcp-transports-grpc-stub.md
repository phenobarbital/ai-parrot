---
id: FW-003
query_id: Q002
type: wiki_query
intent: "Orient: locate MCP client transports (stdio, HTTP, Unix socket, QUIC) to verify the transport inventory and absence of gRPC."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-003 — MCP transports: stdio/http/sse/unix/websocket/streamable_http/quic shipped; a gRPC session + mcp.proto EXIST but are a dead stub

## Summary

Server transports directory (wiki dir page) lists base, grpc_session, http, quic, sse, stdio, streamable_http, unix, websocket. The client-side `_TRANSPORT_SESSIONS` map in `parrot/mcp/integration.py` resolves only stdio/http/sse/unix/websocket (QUIC lazily via `_quic.py`, optional aioquic extra) — **no grpc entry**. `grpc_session.py` (confirmed on disk, 5.7 KB) is an unfinished stub: `from .proto import mcp_pb2, mcp_pb2_grpc` is commented out, it wraps JSON-RPC strings inside a protobuf `MCPRequest`, and no generated `mcp_pb2` module exists anywhere in packages/*/src; a `mcp.proto` file sits beside it. So the brainstorm's "no gRPC transport / no protobuf envelope" VERIFY is correct in substance (nothing wired, nothing generated) but an abandoned attempt exists and should be acknowledged or deleted. `MCPToolProxy` wraps a remote MCP tool as an `AbstractTool` (`get_tool_schema` returns inputSchema directly; results flattened to text via `_extract_result_text`) — a second precedent for the RemoteToolkit, and a reminder that today's remote-tool results are stringified into context.

## Citations

- path: `packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py`
  symbol: `GrpcMCPSession`
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/mcp/transports/grpc_session.py (ingested 2026-07-15)
  excerpt: |
    import grpc
    # from .proto import mcp_pb2, mcp_pb2_grpc
    class GrpcMCPConfig: host, port=50051, use_tls=True, cert_path, use_protobuf_messages=False
    class GrpcMCPSession: send_request() -> mcp_pb2.MCPRequest(json_rpc_message=json.dumps(request))
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/mcp.proto`
  excerpt: |
    (file exists; no generated *_pb2.py anywhere under packages/*/src — grep "mcp_pb2" matched only grpc_session.py)
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  symbol: `_TRANSPORT_SESSIONS`
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/integration.py (score 0.48)
  excerpt: |
    _TRANSPORT_SESSIONS = {"stdio": (...StdioMCPSession), "http": (...HttpMCPSession), "sse": (...), "unix": (...UnixMCPSession), "websocket": (...)}
    # QUIC lives behind the optional ai-parrot-server[mcp] extra (aioquic) — see parrot.mcp._quic
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  symbol: `MCPToolProxy`
  excerpt: |
    class MCPToolProxy(AbstractTool): name = f"mcp_{server_name}_{tool['name']}"; input_schema = inputSchema
        def _execute(...): result = await self.mcp_client.call_tool(...); result_text = self._extract_result_text(result)
        def get_tool_schema(self): return {"name","description","parameters": self.input_schema}
- path: `packages/ai-parrot-server/src/parrot/mcp/transports/quic.py`
  wiki_page_id: dir:packages/ai-parrot-server/src/parrot/mcp/transports (score 0.61)
  excerpt: |
    quic.py — QUIC/HTTP3 MCP Server Implementation; streamable_http.py — MCP Streamable HTTP (2025-03-26)
- path: `packages/ai-parrot/src/parrot/mcp/_quic.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/mcp/_quic.py (score 0.59)
  excerpt: |
    Lazy loader for the optional QUIC/WebTransport MCP transport.

## Notes

- Ledger issue:7a366d6004de notes a duplicate older StdioMCPServer in ai-parrot-server next to the core one — transport code has drifted before; a new binary transport should land in one place.
- [cross-lane: type=grep, intent=check whether grpcio / grpcio-tools / protobuf are declared in any pyproject (grpc_session.py imports grpc at module top — if the dep is absent the module is import-dead)]
- [cross-lane: type=read, intent=read packages/ai-parrot-server/src/parrot/mcp/transports/mcp.proto to record the message shapes already drafted]
