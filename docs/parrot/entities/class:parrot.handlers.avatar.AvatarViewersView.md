---
type: Wiki Entity
title: AvatarViewersView
id: class:parrot.handlers.avatar.AvatarViewersView
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Authenticated endpoint to mint extra subscribe-only viewer tokens (Mode C).
---

# AvatarViewersView

Defined in [`parrot.handlers.avatar`](../summaries/mod:parrot.handlers.avatar.md).

```python
class AvatarViewersView(BaseView)
```

Authenticated endpoint to mint extra subscribe-only viewer tokens (Mode C).

Routed at ``POST /api/v1/avatar/{agent_id}/viewers``.  Authentication mirrors
:class:`AvatarSessionView` — only authenticated callers may mint viewer tokens.

## Methods

- `async def post(self) -> web.Response`
