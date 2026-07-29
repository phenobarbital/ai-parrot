---
type: Concept
title: by_tool_name()
id: func:parrot.mcp.filtering.by_tool_name
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that filters by tool name (simple allowlist).
---

# by_tool_name

```python
def by_tool_name(allowed_names: List[str]) -> ToolPredicate
```

Create predicate that filters by tool name (simple allowlist).

Args:
    allowed_names: List of tool names to allow

Returns:
    ToolPredicate that checks if tool name is in allowed list

Example:
    >>> predicate = by_tool_name(['read_file', 'list_dir', 'write_file'])
    >>> filter_tools(tools, predicate)
