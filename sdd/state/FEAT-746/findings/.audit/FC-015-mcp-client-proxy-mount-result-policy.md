---
id: FC-015
query_id: [Q047]
type: read
intent: "Read the MCP client toolkit (how remote MCP tools become local tools — pattern for RemoteToolkit) plus the server-side per-agent mount and result-size policy."
executed_at: 2026-10-25T22:47:25Z
duration_ms: 0
parent_id: null
depth: 0
---

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
