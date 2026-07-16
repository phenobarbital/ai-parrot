---
type: Wiki Entity
title: AvatarSessionHandle
id: class:parrot.integrations.liveavatar.models.AvatarSessionHandle
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Runtime handle for a LiveAvatar LITE session.
---

# AvatarSessionHandle

Defined in [`parrot.integrations.liveavatar.models`](../summaries/mod:parrot.integrations.liveavatar.models.md).

```python
class AvatarSessionHandle(BaseModel)
```

Runtime handle for a LiveAvatar LITE session.

Carries all the state needed to manage an active avatar session (keep-alive,
stop, WS connection) without re-calling the API.

Attributes:
    session_id: ai-parrot session ID, shared with AgentChat.
    liveavatar_session_id: LiveAvatar session ID returned by the API.
    session_token: Bearer token for ``start_session``.
    ws_url: Avatar media-server WebSocket URL (server-side only).
    tenant_id: Optional tenant identifier for per-tenant opt-in gating.
    agent_name: Logical agent name (used for LiveKit room identity).
