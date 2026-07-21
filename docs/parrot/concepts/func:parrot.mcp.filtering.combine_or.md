---
type: Concept
title: combine_or()
id: func:parrot.mcp.filtering.combine_or
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Combine multiple predicates with OR logic (any can pass).
---

# combine_or

```python
def combine_or(*predicates: ToolPredicate) -> ToolPredicate
```

Combine multiple predicates with OR logic (any can pass).

Args:
    *predicates: Variable number of ToolPredicate functions

Returns:
    ToolPredicate that passes if any predicate passes

Example:
    >>> predicate = combine_or(
    ...     by_role('admin'),
    ...     by_role('super-admin'),
    ...     by_user(['special-user@example.com'])
    ... )
    >>> # Tool available for admins, super-admins, or special user
