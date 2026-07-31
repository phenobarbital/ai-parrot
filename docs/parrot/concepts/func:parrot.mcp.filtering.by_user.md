---
type: Concept
title: by_user()
id: func:parrot.mcp.filtering.by_user
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create predicate that restricts to specific users.
---

# by_user

```python
def by_user(allowed_user_ids: List[str]) -> ToolPredicate
```

Create predicate that restricts to specific users.

Args:
    allowed_user_ids: List of user IDs that can access tools

Returns:
    ToolPredicate that checks user via context

Example:
    >>> predicate = by_user(['admin@example.com', 'superuser@example.com'])
    >>> # Only these users can use the tools
