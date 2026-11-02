---
id: FC-015
query_id: Q028
type: read
intent: "Stdio MCP server dispatch"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-015 — StdioMCPServer: JSON-RPC over stdin/stdout, tools/call as tasks, no auth/identity

## Summary

`LocalMCPServerBase`/`StdioMCPServer` (core) read one JSON-RPC line per request, run `tools/call` as independent asyncio tasks, support `notifications/cancelled`, and explicitly do not depend on aiohttp, auth or resources (those are `RemoteMCPServerBase` in ai-parrot-server). `_handle_request` dispatches `initialize`, `tools/list`, `tools/call`, `ping`; no principal is attached to a call.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/local_server.py`
  lines: 1-8, 54-55, 129-141, 208-232
  symbol: `StdioMCPServer._admit / _handle_request`
  excerpt: |
    Neither depends on aiohttp, auth, or resources — those remain server-only concerns handled by ``RemoteMCPServerBase``
    class StdioMCPServer(LocalMCPServerBase):
    if method == "tools/call":
        task = asyncio.create_task(self._dispatch(request)); self._track(request.get("id"), task)
    elif method == "tools/call": result = await self.handle_tools_call(params)


## Notes

Tool execution goes through `MCPServerBase.handle_tools_call` → `MCPToolAdapter` (server_base.py / adapter.py, not read).
