---
id: F014
query_id: Q027
type: read
intent: "mcp-local CLI command"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-014]
---

# F014 — parrot mcp-local: cwd = project root, config .parrot/mcp-toolkits.yaml, no identity flags

## Summary

`parrot mcp-local NAME [--config] [--include] [--exclude] [--list]` resolves the toolkit from `.parrot/mcp-toolkits.yaml` relative to `Path.cwd()` (the MCP host starts the process in the project dir), redirects logging to stderr, imports `create_toolkit_mcp_server` lazily, and runs `StdioMCPServer.start()` with a SIGTERM handler. There is no user/principal/token option and no environment read for identity.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/local_cli.py`
  lines: 139-186, 217-234
  symbol: `mcp_local`
  excerpt: |
    @click.command("mcp-local")
    @click.argument("name", required=False, default=None)
    @click.option("--config", ...) @click.option("--include", ...) @click.option("--exclude", ...) @click.option("--list", ...)
    def mcp_local(name, config_path, include, exclude, list_toolkits) -> None:
        root = Path.cwd()
        server = create_toolkit_mcp_server(name, root, **overrides)
        asyncio.run(_serve_with_shutdown(server))

## Notes

The `parrot mcp` group is owned by ai-parrot-server (local_cli.py:4-7); core commands are top-level siblings.
