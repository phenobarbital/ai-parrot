---
type: Concept
title: setup_web_hitl()
id: func:parrot.handlers.web_hitl.setup_web_hitl
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Bootstrap a process-wide HumanInteractionManager with a WebHumanChannel.
---

# setup_web_hitl

```python
async def setup_web_hitl(app: web.Application) -> None
```

Bootstrap a process-wide HumanInteractionManager with a WebHumanChannel.

This coroutine is idempotent — it is safe to call multiple times. On each
call it:

1. Checks whether a manager already exists via
   :func:`~parrot.human.get_default_human_manager`.  If one exists,
   checks whether it already has a ``"web"`` channel registered; if so,
   skips entirely.
2. If no manager exists, creates one backed by Redis
   (``parrot.conf.REDIS_URL``), registers a
   :class:`~parrot.human.channels.web.WebHumanChannel` under the name
   ``"web"``, calls :func:`~parrot.human.set_default_human_manager`, and
   awaits ``manager.startup()`` directly.
3. If ``app['user_socket_manager']`` is absent, logs a WARNING but does
   not raise — the bootstrap completes with a degraded state where the
   web channel cannot deliver messages.

This function awaits ``manager.startup()`` itself rather than appending a
new ``on_startup`` hook, so it is safe to call from within an existing
``on_startup`` callback (where ``app.on_startup`` is frozen).

Args:
    app: The :class:`aiohttp.web.Application` instance.
