---
type: Concept
title: by_server()
id: func:parrot.mcp.filtering.by_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that filters by MCP server name.
---

# by_server

```python
def by_server(server_name: str) -> ToolPredicate
```

Create predicate that filters by MCP server name.

Args:
    server_name: Server name (e.g., 'chrome-devtools', 'fireflies')

Returns:
    ToolPredicate that checks if tool belongs to server

Example:
    >>> predicate = by_server('chrome-devtools')
    >>> # Only tools from Chrome DevTools server
