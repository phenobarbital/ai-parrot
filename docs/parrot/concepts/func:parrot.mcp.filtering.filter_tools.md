---
type: Concept
title: filter_tools()
id: func:parrot.mcp.filtering.filter_tools
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Filter tools using a predicate or allowlist.
---

# filter_tools

```python
def filter_tools(tools: List[AbstractTool], predicate: Optional[Union[ToolPredicate, List[str]]], context: Optional['ReadonlyContext']=None) -> List[AbstractTool]
```

Filter tools using a predicate or allowlist.

Args:
    tools: List of tools to filter
    predicate: ToolPredicate, list of tool names, or None
    context: Optional ReadonlyContext for context-aware filtering

Returns:
    Filtered list of tools

Example:
    >>> tools = await client.get_available_tools()
    >>>
    >>> # Filter by allowlist
    >>> filtered = filter_tools(tools, ['read_file', 'list_dir'])
    >>>
    >>> # Filter by predicate
    >>> filtered = filter_tools(
    ...     tools,
    ...     by_permission('admin'),
    ...     context=user_context
    ... )
