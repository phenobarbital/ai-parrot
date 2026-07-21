---
type: Concept
title: close_all_fullmode_sessions()
id: func:parrot.handlers.avatar_fullmode.close_all_fullmode_sessions
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Best-effort teardown of any lingering FULL mode sessions on shutdown.
---

# close_all_fullmode_sessions

```python
async def close_all_fullmode_sessions(app: web.Application) -> None
```

Best-effort teardown of any lingering FULL mode sessions on shutdown.

Registered as an ``on_cleanup`` callback by the bot manager.  Iterates the
session store, stops each session, and closes its client.
