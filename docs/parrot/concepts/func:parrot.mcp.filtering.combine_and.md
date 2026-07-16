---
type: Concept
title: combine_and()
id: func:parrot.mcp.filtering.combine_and
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Combine multiple predicates with AND logic (all must pass).
---

# combine_and

```python
def combine_and(*predicates: ToolPredicate) -> ToolPredicate
```

Combine multiple predicates with AND logic (all must pass).

Args:
    *predicates: Variable number of ToolPredicate functions

Returns:
    ToolPredicate that passes only if all predicates pass

Example:
    >>> predicate = combine_and(
    ...     by_role('admin'),
    ...     by_organization(['acme-corp']),
    ...     by_permission('use_external_tools')
    ... )
    >>> # Tool available only if user is admin AND in org AND has permission
