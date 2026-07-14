---
type: Wiki Entity
title: PermissionContext
id: class:parrot.auth.permission.PermissionContext
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Request-scoped wrapper grouping session with extra context.
---

# PermissionContext

Defined in [`parrot.auth.permission`](../summaries/mod:parrot.auth.permission.md).

```python
class PermissionContext
```

Request-scoped wrapper grouping session with extra context.

This is the primary object passed through the permission checking pipeline.
It wraps an immutable UserSession with mutable request-specific metadata.

Attributes:
    session: The underlying UserSession with identity and roles.
    request_id: Optional request/correlation ID for tracing.
    channel: Optional originating channel (e.g., ``"telegram"``,
        ``"agentalk"``, ``"teams"``, ``"api"``). Toolkits that perform
        per-user credential resolution (OAuth 2.0 3LO, etc.) use this to
        scope token storage and authorization callbacks. ``None`` by
        default for backward compatibility with callers that don't yet
        propagate the channel.
    trace_context: Optional W3C-compatible trace context for lifecycle event
        propagation across agent → tool and agent → sub-agent boundaries.
        ``None`` by default; populated by TASK-1193 (AbstractBot) and read
        by TASK-1195 (AbstractTool) to mint child spans.
    extra: Additional request-scoped metadata (e.g., source IP, API version).

Example:
    >>> session = UserSession(
    ...     user_id="user-123",
    ...     tenant_id="acme-corp",
    ...     roles=frozenset({'admin'})
    ... )
    >>> ctx = PermissionContext(
    ...     session=session,
    ...     request_id="req-456",
    ...     channel="telegram",
    ...     extra={"source": "api", "version": "v2"}
    ... )
    >>> ctx.user_id
    'user-123'
    >>> ctx.channel
    'telegram'
    >>> ctx.roles
    frozenset({'admin'})

## Methods

- `def user_id(self) -> str` — Get the user ID from the underlying session.
- `def tenant_id(self) -> str` — Get the tenant ID from the underlying session.
- `def roles(self) -> frozenset[str]` — Get the roles from the underlying session.
- `def has_role(self, role: str) -> bool` — Check if session has a specific role.
- `def has_any_role(self, roles: set[str] | frozenset[str]) -> bool` — Check if session has any of the specified roles.
