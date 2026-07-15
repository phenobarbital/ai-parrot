---
type: Concept
title: by_scope()
id: func:parrot.mcp.filtering.by_scope
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create predicate that requires OAuth scope.
---

# by_scope

```python
def by_scope(required_scope: str) -> ToolPredicate
```

Create predicate that requires OAuth scope.

Args:
    required_scope: OAuth scope (e.g., 'read:calendar', 'write:email')

Returns:
    ToolPredicate that checks OAuth scopes via context

Example:
    >>> predicate = by_scope('write:email')
    >>> # Only users with email write scope
