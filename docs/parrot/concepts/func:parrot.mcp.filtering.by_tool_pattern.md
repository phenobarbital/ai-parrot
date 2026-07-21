---
type: Concept
title: by_tool_pattern()
id: func:parrot.mcp.filtering.by_tool_pattern
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that filters tools by name pattern.
---

# by_tool_pattern

```python
def by_tool_pattern(pattern: str) -> ToolPredicate
```

Create predicate that filters tools by name pattern.

Args:
    pattern: Glob-style pattern (e.g., 'mcp_*_read_*', 'chrome_*')

Returns:
    ToolPredicate that matches tool names against pattern

Example:
    >>> predicate = by_tool_pattern('mcp_admin_*')
    >>> # Only admin tools from MCP servers
