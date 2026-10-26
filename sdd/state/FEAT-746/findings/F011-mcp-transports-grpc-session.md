---
id: F011
query_id: Q002, [Q029, Q046], [Q047]
type: read
intent: "MCP transports inventory: confirm stdio / http / unix / quic and the state of gRPC; read the transport base as the pattern for a new binary transport."
executed_at: 2026-10-25T22:43:31Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: FC-003, FC-015, FW-003
lane_origin: FC-003-mcp-transports-grpc-session, FC-015-mcp-client-proxy-mount-result-policy, FW-003-mcp-transports-grpc-stub
---

# F011 — MCP transports: stdio/http/streamable-http/sse/unix/websocket/quic shipped; a gRPC session exists but its protobuf import is commented out (JSON-RPC over gRPC, not a typed envelope)

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


<!-- merged from FC-015 -->

# FC-015 — MCPClient + MCPToolProxy is the existing "remote tools become local AbstractTools" pattern; AgentMCPMount mounts agents as MCP endpoints with PBAC; result_policy caps tool results by approximate tokens

## Summary

Core `parrot/mcp/integration.py` (1930 lines): `MCPClient(config: MCPServerConfig, tool_name_prefix)` with `_detect_transport`, `connect`, `call_tool(tool_name, arguments, headers)`, `get_tools(context) -> List[MCPToolProxy]` and `get_tools_for_context`; `MCPToolProxy(AbstractTool)` (line 92) wraps each remote tool so ToolManager can register it; `MCPEnabledMixin` (line 1356) wires it into bots. Server `parrot/mcp/agent_mount.py` `AgentMCPMount` builds one Streamable-HTTP MCP server per exposed agent (mirroring `A2AServer.setup()`), resolves the agent by name on every call, and gates every per-agent and aggregate server through `_guard()`/`PBACGuard` with canonical resource `mcp:agent:{name}:tool:{tool}`. Server `parrot/mcp/result_policy.py` (FEAT-477 G7/G8) enforces a per-tool result cap (`MCPToolDeclaration.max_result_tokens` or `AgentMCPMountConfig.max_result_tokens`) by a char-count heuristic (`_approx_tokens`, no real tokenizer) with deterministic truncation/pagination and `run_with_deadline` for `call_deadline_seconds`. These are the closest precedents for RemoteToolkit (D8), mounting, and server-side materialization caps.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 92
  symbol: `MCPToolProxy`
  excerpt: |
    class MCPToolProxy(AbstractTool):
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 363-380
  symbol: `MCPClient`
  excerpt: |
    class MCPClient:
        """Complete MCP client with stdio and HTTP transport support."""
        def __init__(self, config: MCPServerConfig, tool_name_prefix: Optional[str] = None):
            self.tool_name_prefix = tool_name_prefix or config.tool_name_prefix or f"mcp_{config.name}"
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 392-422
  symbol: `MCPClient.connect`, `call_tool`
  excerpt: |
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 481-509
  symbol: `MCPClient.get_tools_for_context`, `get_tools`
  excerpt: |
    async def get_tools(self, context: Optional["ReadonlyContext"] = None) -> List[MCPToolProxy]:
- path: `packages/ai-parrot/src/parrot/mcp/integration.py`
  lines: 1356
  symbol: `MCPEnabledMixin`
- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 133
  symbol: `MCPClientConfig`
- path: `packages/ai-parrot/src/parrot/tools/mcp_mixin.py`
  lines: 31
  symbol: `MCPToolManagerMixin`
- path: `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py`
  lines: 1-16
  symbol: module docstring
  excerpt: |
    """`AgentMCPMount` — per-agent Streamable HTTP endpoints (FEAT-477, Module 2).
    per exposed agent at {base_path}/{agent_name}, mirroring the mount pattern
    A2AServer.setup() already proves (a2a/server.py:231).
    to the same canonical PBAC resource, mcp:agent:{name}:tool:{tool}
- path: `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py`
  lines: 124-184
  symbol: `_AgentBoundMCPServer`, `_guard`, `handle_tools_list`, `handle_tools_call`
- path: `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py`
  lines: 265-298
  symbol: `AgentMCPMount`
- path: `packages/ai-parrot-server/src/parrot/mcp/result_policy.py`
  lines: 1-20
  symbol: module docstring
  excerpt: |
    """Result size policy + per-call deadline (FEAT-477, Module 3, G7/G8).
    Tool responses must stay under the ~30,000-token custom-connector ceiling,
    **enforced by the adapter layer, not left to method authors**
    No token counter exists anywhere in parrot.mcp — :func:`_approx_tokens`
- path: `packages/ai-parrot-server/src/parrot/mcp/result_policy.py`
  lines: 53-134
  symbol: `_approx_tokens`, `resolve_cap`, `apply_size_policy`
  excerpt: |
    def _approx_tokens(serialized: str) -> int:
    def resolve_cap(declaration: Any, mount_config: Any) -> int:
    def apply_size_policy(result: Any, cap: int) -> dict[str, Any]:

## Notes

The MCP adapter half of D14 ("expose a mounted category as an MCP server") maps almost 1:1 onto `AgentMCPMount` + `RemoteMCPServerBase.register_tool`. `MCPToolProxy` returns MCP JSON content — no handle semantics.


<!-- merged from FW-003 -->

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
