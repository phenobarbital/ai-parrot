---
id: F040
query_id: Q002
type: wiki_query
intent: "Orient: parrot mcp-local — per-toolkit stdio MCP servers for Claude Code / Codex and how they are configured."
executed_at: 2026-10-30T15:21:00Z
duration_ms: 2100
parent_id: null
depth: 1
merged_from: [FW-003]
---

# F040 — `parrot mcp-local` / `StdioMCPServer`: a tools/call carries no identity; the process is the trust boundary

## Summary

`parrot mcp-local NAME` (`parrot/mcp/local_cli.py`, FEAT-485; lazy command at `cli/__init__.py:116`) resolves an `AbstractToolkit` by name from a toolkits config and serves it over stdio via `create_toolkit_mcp_server` → `StdioMCPServer` (`parrot/mcp/local_server.py`). All logging goes to stderr; stdout is the JSON-RPC channel. The dispatch path is `_admit` → (`tools/call` as its own task) `_dispatch` → `_handle_request` → `MCPServerBase.handle_tools_call(params)` → `adapter.execute(arguments)`. **No principal, `PermissionContext`, `user_id` or bearer appears anywhere on this path** — the only inputs are `tool name` + `arguments`; whoever can write to the process's stdin can call every tool. agentd's `mcp-serve` and ai-parrot-server's `transports/stdio.py` reuse the same `StdioMCPServer` (Q013 inbound edges).

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 116
  symbol: `cli._lazy_commands`
  excerpt: |
    "mcp-local": "parrot.mcp.local_cli",
- path: `packages/ai-parrot/src/parrot/mcp/local_cli.py`
  lines: 1-12
  symbol: module docstring
  excerpt: |
    `parrot mcp-local` — serve an ``AbstractToolkit`` as a local stdio MCP server.
    FEAT-485. ... The ``parrot mcp`` group is owned by ai-parrot-server's ``parrot.mcp.cli`` module ...
    hence a sibling top-level command instead (precedent: ``mcp-serve`` for agentd).
- path: `packages/ai-parrot/src/parrot/mcp/local_cli.py`
  symbol: `mcp_local`
  excerpt: |
    def mcp_local(name, config_path, include, exclude, list_toolkits): Serve NAME as a local stdio MCP server.
- path: `packages/ai-parrot/src/parrot/mcp/local_server.py`
  lines: 36-54
  symbol: `LocalMCPServerBase` / `StdioMCPServer`
  excerpt: |
    class LocalMCPServerBase(MCPServerBase):      # :36
    class StdioMCPServer(LocalMCPServerBase):     # :54
- path: `packages/ai-parrot/src/parrot/mcp/local_server.py`
  lines: 129-143
  symbol: `StdioMCPServer._admit`
  excerpt: |
    if method == "tools/call":
        task = asyncio.create_task(self._dispatch(request))
        self._track(request.get("id"), task)
- path: `packages/ai-parrot/src/parrot/mcp/local_server.py`
  lines: 208-232
  symbol: `StdioMCPServer._handle_request`
  excerpt: |
    elif method == "tools/call":
        result = await self.handle_tools_call(params)
- path: `packages/ai-parrot/src/parrot/mcp/server_base.py`
  lines: 111-124
  symbol: `MCPServerBase.handle_tools_call`
  excerpt: |
    tool_name = params.get("name"); arguments = params.get("arguments", {})
    adapter = self.tools[tool_name]
    return await adapter.execute(arguments)
- path: `packages/ai-parrot/src/parrot/mcp/server_base.py`
  lines: 48
  symbol: `LocalServerConfig`
  excerpt: |
    class LocalServerConfig:

## Notes

Wiki: `dir:packages/ai-parrot/src/parrot/mcp` (1.00), `TASK-3506` lifecycle (0.87), `TASK-2646` factory (0.46), `TASK-2647` CLI (0.44), `sdd/specs/expose-toolkits-as-local-mcp.spec.md` (0.14), `file:...mcp/local_cli.py` (0.12), `TASK-2078` (0.08). Memory `mem-9fffc20232df`: stdin-EOF kills the server (host shows "Connection closed"). Implication for S-4: a per-call principal for stdio servers cannot come from the MCP request (hosts like Claude Code send none); it must be bound at process start (env / config written by `hosts.py`) or looked up from a local login file — same shape as agentd's connection-time binding (FW-005).
[cross-lane: type=grep, intent=does `adapter.execute` (parrot/mcp/adapter.py) inject any `_permission_context`/`_cred_user_id` kwargs before AbstractTool.execute]
[cross-lane: type=read, intent=hosts.py — what env/args the generated Claude Code / Codex server entry carries]
