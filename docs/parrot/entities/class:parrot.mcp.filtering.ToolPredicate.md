---
type: Wiki Entity
title: ToolPredicate
id: class:parrot.mcp.filtering.ToolPredicate
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol for tool filtering logic.
---

# ToolPredicate

Defined in [`parrot.mcp.filtering`](../summaries/mod:parrot.mcp.filtering.md).

```python
class ToolPredicate(Protocol)
```

Protocol for tool filtering logic.

A ToolPredicate is a callable that determines if a tool should be
available in a given context. It receives:
- tool: The AbstractTool to evaluate
- context: Optional ReadonlyContext with user/org information

Returns True if tool should be available, False otherwise.

Example:
    >>> def my_predicate(tool: AbstractTool, context: Optional[ReadonlyContext]) -> bool:
    ...     if not context:
    ...         return False
    ...     return context.has_permission('admin')
    >>>
    >>> # Use with MCPClient
    >>> client = MCPClient(config, tool_filter=my_predicate)
