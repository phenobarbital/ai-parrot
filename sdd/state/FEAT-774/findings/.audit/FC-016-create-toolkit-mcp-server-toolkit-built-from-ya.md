---
id: FC-016
query_id: Q029
type: read
intent: "Toolkit stdio server factory"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-016 — create_toolkit_mcp_server: toolkit built from YAML kwargs (+LLM), tools registered; no broker, no principal

## Summary

`create_toolkit_mcp_server(name, root, **overrides)` loads `.parrot/mcp-toolkits.yaml`, imports the class path under `redirect_stdout(stderr)`, optionally builds an LLM via `LLMFactory.create`, instantiates `toolkit_cls(**kwargs)`, filters tools (include/exclude/llm_dependent) and registers them on `_ToolkitStdioMCPServer` (owns the toolkit for cleanup). Nothing sets a broker, credentials or a `PermissionContext`; toolkits needing credentials must get them from constructor kwargs/env.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 137-141, 176-183, 217-224, 260-264
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
  lines: 37-60
  symbol: `_ToolkitStdioMCPServer`
  excerpt: |
    class _ToolkitStdioMCPServer(StdioMCPServer): def __init__(self, config, toolkit)


## Notes

Seam for S-4: this factory is where a CLI principal + remote CredentialStore/broker would have to be injected into the toolkit (e.g. `JiraToolkit` with `credential_provider="jira"`).
