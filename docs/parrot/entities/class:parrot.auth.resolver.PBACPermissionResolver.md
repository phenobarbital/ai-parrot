---
type: Wiki Entity
title: PBACPermissionResolver
id: class:parrot.auth.resolver.PBACPermissionResolver
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: PBAC-backed permission resolver — Layer 2 safety net.
relates_to:
- concept: class:parrot.auth.resolver.AbstractPermissionResolver
  rel: extends
---

# PBACPermissionResolver

Defined in [`parrot.auth.resolver`](../summaries/mod:parrot.auth.resolver.md).

```python
class PBACPermissionResolver(AbstractPermissionResolver)
```

PBAC-backed permission resolver — Layer 2 safety net.

Wraps navigator-auth's ``PolicyEvaluator`` and implements the
``AbstractPermissionResolver`` interface so that tool executions are
checked against YAML-defined PBAC policies.

**Role in the architecture**:
Primary enforcement (Layer 1) happens at the handler level via
``Guardian.filter_resources()``.  This resolver provides defense-in-depth
by re-checking policies inside ``AbstractTool.execute()`` (Layer 2).
A denial at this layer indicates that a tool slipped through the handler
filter — it is logged as a warning for audit purposes.

Both this resolver and the handler-level Guardian MUST share the same
``PolicyEvaluator`` instance (wired by ``setup_pbac()``) to guarantee
consistent decisions.

Attributes:
    _evaluator: Shared ``PolicyEvaluator`` instance.
    logger: Standard Python logger for denial audit events.

Example::

    resolver = PBACPermissionResolver(evaluator=evaluator)
    tool_manager.set_resolver(resolver)

## Methods

- `async def can_execute(self, context: PermissionContext, tool_name: str, required_permissions: set[str]) -> bool` — Layer 2 PBAC check — evaluate tool execution permission.
- `async def filter_tools(self, context: PermissionContext, tools: list[Any]) -> list[Any]` — Layer 1 PBAC filter — batch filter tools by policy.
