---
type: Concept
title: by_permission()
id: func:parrot.mcp.filtering.by_permission
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create predicate that requires specific permission.
---

# by_permission

```python
def by_permission(required_permission: str) -> ToolPredicate
```

Create predicate that requires specific permission.

Args:
    required_permission: Permission string (e.g., 'use_mcp_tools', 'admin')

Returns:
    ToolPredicate that checks user permission via context

Example:
    >>> predicate = by_permission('use_external_tools')
    >>> # Only tools with users having 'use_external_tools' permission
