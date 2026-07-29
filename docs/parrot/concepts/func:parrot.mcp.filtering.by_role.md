---
type: Concept
title: by_role()
id: func:parrot.mcp.filtering.by_role
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that requires specific role.
---

# by_role

```python
def by_role(required_role: str) -> ToolPredicate
```

Create predicate that requires specific role.

Args:
    required_role: Role name (e.g., 'admin', 'hr', 'finance')

Returns:
    ToolPredicate that checks user role via context

Example:
    >>> predicate = by_role('admin')
    >>> # Only admins can use these tools
