---
type: Wiki Entity
title: ReadonlyContext
id: class:parrot.mcp.context.ReadonlyContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Immutable context passed to tool operations.
---

# ReadonlyContext

Defined in [`parrot.mcp.context`](../summaries/mod:parrot.mcp.context.md).

```python
class ReadonlyContext(BaseModel)
```

Immutable context passed to tool operations.

This context provides information about the agent, user, and organizational
context for tool execution. It enables:
- Tool filtering based on user roles/scopes
- Dynamic header generation
- Multi-tenant isolation
- Rate limiting by user/organization

Example:
    >>> ctx = ReadonlyContext(
    ...     agent_id="hr-agent",
    ...     user_id="user-123",
    ...     organization_id="acme-corp",
    ...     roles=["admin", "hr"],
    ...     scopes=["read:employees", "write:employees"]
    ... )
    >>> # Context is immutable
    >>> ctx.user_id = "other"  # Raises ValidationError
