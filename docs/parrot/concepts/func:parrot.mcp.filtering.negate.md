---
type: Concept
title: negate()
id: func:parrot.mcp.filtering.negate
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Negate a predicate (invert boolean result).
---

# negate

```python
def negate(predicate: ToolPredicate) -> ToolPredicate
```

Negate a predicate (invert boolean result).

Args:
    predicate: ToolPredicate to negate

Returns:
    ToolPredicate that returns the opposite of input predicate

Example:
    >>> # Allow all except delete operations
    >>> predicate = negate(by_tool_pattern('*_delete_*'))
