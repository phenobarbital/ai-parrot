---
type: Wiki Entity
title: DenyAllResolver
id: class:parrot.auth.resolver.DenyAllResolver
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolver that denies all tool executions.
relates_to:
- concept: class:parrot.auth.resolver.AbstractPermissionResolver
  rel: extends
---

# DenyAllResolver

Defined in [`parrot.auth.resolver`](../summaries/mod:parrot.auth.resolver.md).

```python
class DenyAllResolver(AbstractPermissionResolver)
```

Resolver that denies all tool executions.

Use this for lockdown scenarios or as a fail-safe default.

## Methods

- `async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool` — Always returns False for restricted tools, True for unrestricted.
