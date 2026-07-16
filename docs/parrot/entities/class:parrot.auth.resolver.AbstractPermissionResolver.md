---
type: Wiki Entity
title: AbstractPermissionResolver
id: class:parrot.auth.resolver.AbstractPermissionResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pluggable resolver for tool permission checks.
---

# AbstractPermissionResolver

Defined in [`parrot.auth.resolver`](../summaries/mod:parrot.auth.resolver.md).

```python
class AbstractPermissionResolver(ABC)
```

Pluggable resolver for tool permission checks.

This ABC defines the interface for permission resolution. Implementations
can use different backends (in-memory, Redis, database) and different
permission models (RBAC, ABAC, custom).

The two main methods serve different enforcement layers:
- can_execute(): Layer 2 reactive enforcement per tool call
- filter_tools(): Layer 1 preventive filtering at agent startup

Example:
    >>> class CustomResolver(AbstractPermissionResolver):
    ...     async def can_execute(self, context, tool_name, required_permissions):
    ...         # Custom logic here
    ...         return True

## Methods

- `async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool` — Check if user in context may execute the tool.
- `async def filter_tools(self, context: PermissionContext, tools: list[Any]) -> list[Any]` — Return subset of tools the user is allowed to execute.
