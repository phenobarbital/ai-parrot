---
type: Concept
title: exclude_by_tool_name()
id: func:parrot.mcp.filtering.exclude_by_tool_name
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that blocks specific tool names (blocklist).
---

# exclude_by_tool_name

```python
def exclude_by_tool_name(blocked_names: List[str]) -> ToolPredicate
```

Create predicate that blocks specific tool names (blocklist).

Args:
    blocked_names: List of tool names to block

Returns:
    ToolPredicate that denies tools in blocked list

Example:
    >>> predicate = exclude_by_tool_name(['delete_file', 'format_drive'])
    >>> filter_tools(tools, predicate)
