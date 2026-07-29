---
type: Concept
title: close_all_avatar_sessions()
id: func:parrot.handlers.avatar.close_all_avatar_sessions
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Best-effort teardown of any lingering avatar sessions on shutdown.
---

# close_all_avatar_sessions

```python
async def close_all_avatar_sessions(app: web.Application) -> None
```

Best-effort teardown of any lingering avatar sessions on shutdown.

Registered as an ``on_cleanup`` callback by the bot manager.  Iterates the
session store, stops each LiveAvatar session or direct-audio publisher
(FEAT-256 avatar-OFF path) and closes its client.
