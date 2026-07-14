---
type: Wiki Entity
title: AgentSharingHandler
id: class:parrot.handlers.agents.sharing.AgentSharingHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Stub handler for ephemeral agent sharing.
---

# AgentSharingHandler

Defined in [`parrot.handlers.agents.sharing`](../summaries/mod:parrot.handlers.agents.sharing.md).

```python
class AgentSharingHandler
```

Stub handler for ephemeral agent sharing.

All methods raise :class:`NotImplementedError` until the follow-up
feature implements the sharing scheme.

## Methods

- `async def post(self, request: web.Request) -> web.Response` — Share an agent with another user (not yet implemented).
- `async def get(self, request: web.Request) -> web.Response` — List users with access to an agent (not yet implemented).
- `async def delete(self, request: web.Request) -> web.Response` — Revoke access to an agent (not yet implemented).
