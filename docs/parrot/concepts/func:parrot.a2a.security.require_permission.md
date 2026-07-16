---
type: Concept
title: require_permission()
id: func:parrot.a2a.security.require_permission
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to require a specific permission.
---

# require_permission

```python
def require_permission(permission: str)
```

Decorator to require a specific permission.

Example:
    @require_permission("skill:admin")
    async def admin_handler(request):
        ...
