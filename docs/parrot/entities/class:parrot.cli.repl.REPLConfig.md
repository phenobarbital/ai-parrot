---
type: Wiki Entity
title: REPLConfig
id: class:parrot.cli.repl.REPLConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for an agent REPL session.
---

# REPLConfig

Defined in [`parrot.cli.repl`](../summaries/mod:parrot.cli.repl.md).

```python
class REPLConfig(BaseModel)
```

Configuration for an agent REPL session.

Attributes:
    agent_name: The name of the agent being conversed with.
    streaming: Whether to use streaming token delivery (default True).
    server_url: Optional server URL for server-mode proxy.
    session_id: Unique session identifier (auto-generated if not provided).
    user_id: User identifier sent with each request.
    permission_context: Optional FEAT-264/266 permission context (a
        ``parrot.auth.permission.PermissionContext``) threaded into
        ``bot.ask``/``bot.ask_stream`` so the credential broker seam
        (``ToolManager`` → ``AbstractTool``) sees ``channel``/``user_id``
        for per-user resolvers like the O365 device-code flow. Typed as
        ``Any`` (not the concrete dataclass) to avoid forcing pydantic
        to resolve ``PermissionContext``'s own TYPE_CHECKING-only
        forward refs at schema-build time. ``None`` by default — agents
        that don't declare broker-backed credentials are completely
        unaffected.
