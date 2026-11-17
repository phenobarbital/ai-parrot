---
id: F016
query_id: [Q029, Q009]
type: [read, wiki_page]
intent: "Toolkit stdio server factory"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-016, FW-004]
---

# F016 — create_toolkit_mcp_server: toolkit built from YAML kwargs (+LLM), tools registered; no broker, no principal

## Summary

**[FC-016]** `create_toolkit_mcp_server(name, root, **overrides)` loads `.parrot/mcp-toolkits.yaml`, imports the class path under `redirect_stdout(stderr)`, optionally builds an LLM via `LLMFactory.create`, instantiates `toolkit_cls(**kwargs)`, filters tools (include/exclude/llm_dependent) and registers them on `_ToolkitStdioMCPServer` (owns the toolkit for cleanup). Nothing sets a broker, credentials or a `PermissionContext`; toolkits needing credentials must get them from constructor kwargs/env.

**[FW-004]** `parrot/mcp/toolkit_server.py` (FEAT-485/580) exposes `create_toolkit_mcp_server(name, root) -> StdioMCPServer`. It loads `load_toolkits_config` (`parrot.mcp.toolkit_config`), imports the toolkit class under `contextlib.redirect_stdout(sys.stderr)` (stdout purity), optionally wires an LLM via a lazily imported `LLMFactory`, instantiates the toolkit ONCE, applies include/exclude/llm_dependent filtering, and wraps it in `_ToolkitStdioMCPServer`, which releases the toolkit's `_open()`-acquired resources on stop (bounded by `_CLEANUP_TIMEOUT_SECONDS = 10.0`). The outline shows no `CredentialBroker`, `set_broker`, `PermissionContext` or `user_id` — toolkit credentials are whatever the toolkit's constructor reads (config / env) at process start. A per-principal connection for a stdio toolkit therefore needs a new injection point (factory or adapter), not a tweak to an existing one.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 137-141
  symbol: `create_toolkit_mcp_server`
  excerpt: |
    def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer:
        cfg = load_toolkits_config(root, config_path=...)
        section = cfg.toolkits[name]
        kwargs = dict(section.kwargs); if llm_client is not None: kwargs["llm_client"] = llm_client
        toolkit = toolkit_cls(**kwargs)
        server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit)
        server.register_tools(filtered_tools)
- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 37-62
  symbol: `_ToolkitStdioMCPServer`
  excerpt: |
    class _ToolkitStdioMCPServer(StdioMCPServer): def __init__(self, config, toolkit)
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

## Notes

**[FC-016]** Seam for S-4: this factory is where a CLI principal + remote CredentialStore/broker would have to be injected into the toolkit (e.g. `JiraToolkit` with `credential_provider="jira"`).

**[FW-004]** Wiki page `file:packages/ai-parrot/src/parrot/mcp/toolkit_server.py` (module). `_CLEANUP_TIMEOUT_SECONDS` at ~:36. The `LLMFactory` comment documents navconfig's eager `print()` to stdout — any S-4 code that imports navconfig/`parrot.auth` inside a stdio server must do so under the same stderr redirect.
[cross-lane: type=read, intent=toolkit_server.py:137-end — signature of create_toolkit_mcp_server and how toolkit kwargs/config reach the constructor]
[cross-lane: type=read, intent=toolkit_config.py — fields of the per-toolkit config entry (env, secrets, user)]
