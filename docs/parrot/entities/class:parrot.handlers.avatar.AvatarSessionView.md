---
type: Wiki Entity
title: AvatarSessionView
id: class:parrot.handlers.avatar.AvatarSessionView
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Authenticated entrypoint for the avatar start/stop actions.
---

# AvatarSessionView

Defined in [`parrot.handlers.avatar`](../summaries/mod:parrot.handlers.avatar.md).

```python
class AvatarSessionView(BaseView)
```

Authenticated entrypoint for the avatar start/stop actions.

Routed at ``/api/v1/agents/avatar/{agent_id}/{action}`` where ``action`` is
``start`` or ``stop``.  Authentication/session decorators match
:class:`AgentTalk`, so unauthenticated callers are rejected before any
avatar session is created or destroyed.

## Methods

- `async def post(self) -> web.Response`
- `async def get(self) -> web.Response`
