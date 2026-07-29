---
type: Wiki Entity
title: AllowAllResolver
id: class:parrot.auth.resolver.AllowAllResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolver that allows all tool executions.
relates_to:
- concept: class:parrot.auth.resolver.AbstractPermissionResolver
  rel: extends
---

# AllowAllResolver

Defined in [`parrot.auth.resolver`](../summaries/mod:parrot.auth.resolver.md).

```python
class AllowAllResolver(AbstractPermissionResolver)
```

Resolver that allows all tool executions.

Use this for development/testing or when permission checks are
handled elsewhere (e.g., at the API gateway level).

## Methods

- `async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool` — Always returns True.
