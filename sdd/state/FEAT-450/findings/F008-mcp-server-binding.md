---
id: F008
query_id: Q013
type: read
intent: Confirm MCP server binds a single store resolved from one project root
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F008 — create_wiki_mcp_server(root) opens one store from the root's wiki.json

## Summary
`create_wiki_mcp_server(root)` (mcp_server.py:66-146) loads config, calls `create_wiki_store`
(95 arangodb / 105 sqlite-memory) with `config.storage_path(root)`, then
`create_wiki_tools(store, root=root, config=config)` (108) and `server.register_tools(tools)`
(142); optional Obsidian vault tools (112-144). `main()` (148-185) resolves root via
`find_project_root(_INVOCATION_CWD)`. Swapping in a federated store at line 105/108 gives the MCP
tools namespace support; registration in `.mcp.json` (`wikitoolkit mcp`, cwd-based) is unchanged.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 66-146
  symbol: `create_wiki_mcp_server`
  excerpt: |
    storage = config.storage_path(root)
    store = create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)  # 105
    tools = create_wiki_tools(store, root=root, config=config)                              # 108
    server.register_tools(tools)                                                            # 142
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 148-185
  symbol: `main`
- path: `.mcp.json`
  lines: 1-10
  excerpt: |
    "wikitoolkit": {"command": "${CLAUDE_PROJECT_DIR}/.venv/bin/wikitoolkit", "args": ["mcp"]}
