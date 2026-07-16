---
type: Concept
title: require_role()
id: func:parrot.a2a.security.require_role
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to require a specific role.
---

# require_role

```python
def require_role(role: str)
```

Decorator to require a specific role.

Example:
    @require_role("admin")
    async def admin_handler(request):
        ...
