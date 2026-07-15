---
type: Wiki Entity
title: A2ASecurityMiddleware
id: class:parrot.a2a.security.A2ASecurityMiddleware
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Security middleware for A2AServer.
---

# A2ASecurityMiddleware

Defined in [`parrot.a2a.security`](../summaries/mod:parrot.a2a.security.md).

```python
class A2ASecurityMiddleware
```

Security middleware for A2AServer.

Handles authentication and authorization for incoming A2A requests.

Example:
    middleware = A2ASecurityMiddleware(
        jwt_authenticator=jwt_auth,
        credential_provider=provider,
        default_policy=SecurityPolicy(require_auth=True),
    )

    # Add to A2AServer
    a2a_server.add_security(middleware)

    # Or use directly as aiohttp middleware
    app.middlewares.append(middleware.middleware)

## Methods

- `def set_skill_policy(self, skill_id: str, policy: SecurityPolicy) -> None` — Set security policy for a specific skill.
- `def get_policy(self, skill_id: Optional[str]=None) -> SecurityPolicy` — Get policy for a skill or the default.
- `async def authenticate(self, request: web.Request) -> Optional[CallerIdentity]` — Authenticate an incoming request.
- `async def authorize(self, identity: CallerIdentity, policy: SecurityPolicy, skill_id: Optional[str]=None) -> Tuple[bool, Optional[str]]` — Authorize an authenticated identity against a policy.
- `async def middleware(self, request: web.Request, handler: Callable) -> web.Response` — aiohttp middleware for security.
