---
id: FW-004
query_id: Q009
type: wiki_page
intent: "Read the wiki page of the toolkit stdio server (tool execution path, permission context, broker)."
executed_at: 2026-10-30T15:21:30Z
duration_ms: 900
parent_id: null
depth: 1
---

# FW-004 — `create_toolkit_mcp_server`: toolkit built once at startup from config, owned by the server; no broker, no per-user identity

## Summary

`parrot/mcp/toolkit_server.py` (FEAT-485/580) exposes `create_toolkit_mcp_server(name, root) -> StdioMCPServer`. It loads `load_toolkits_config` (`parrot.mcp.toolkit_config`), imports the toolkit class under `contextlib.redirect_stdout(sys.stderr)` (stdout purity), optionally wires an LLM via a lazily imported `LLMFactory`, instantiates the toolkit ONCE, applies include/exclude/llm_dependent filtering, and wraps it in `_ToolkitStdioMCPServer`, which releases the toolkit's `_open()`-acquired resources on stop (bounded by `_CLEANUP_TIMEOUT_SECONDS = 10.0`). The outline shows no `CredentialBroker`, `set_broker`, `PermissionContext` or `user_id` — toolkit credentials are whatever the toolkit's constructor reads (config / env) at process start. A per-principal connection for a stdio toolkit therefore needs a new injection point (factory or adapter), not a tweak to an existing one.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 1-5
  symbol: module docstring
  excerpt: |
    Toolkit MCP server factory for local stdio servers.
    FEAT-485: Creates a StdioMCPServer for any AbstractToolkit-based class,
    with optional LLM wiring and tool filtering (include/exclude/llm_dependent).

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 24-30
  symbol: imports
  excerpt: |
    from parrot.mcp.local_server import StdioMCPServer
    from parrot.mcp.server_base import LocalServerConfig
    from parrot.mcp.toolkit_config import load_toolkits_config
    from parrot.tools.toolkit import AbstractToolkit

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 38-62
  symbol: `_ToolkitStdioMCPServer`
  excerpt: |
    class _ToolkitStdioMCPServer(StdioMCPServer):
        def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) -> None:
            super().__init__(config); self._owned_toolkit = toolkit
        async def start(self) -> None:   # :62

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 137
  symbol: `create_toolkit_mcp_server`
  excerpt: |
    def create_toolkit_mcp_server(

## Notes

Wiki page `file:packages/ai-parrot/src/parrot/mcp/toolkit_server.py` (module). `_CLEANUP_TIMEOUT_SECONDS` at ~:36. The `LLMFactory` comment documents navconfig's eager `print()` to stdout — any S-4 code that imports navconfig/`parrot.auth` inside a stdio server must do so under the same stderr redirect.
[cross-lane: type=read, intent=toolkit_server.py:137-end — signature of create_toolkit_mcp_server and how toolkit kwargs/config reach the constructor]
[cross-lane: type=read, intent=toolkit_config.py — fields of the per-toolkit config entry (env, secrets, user)]
