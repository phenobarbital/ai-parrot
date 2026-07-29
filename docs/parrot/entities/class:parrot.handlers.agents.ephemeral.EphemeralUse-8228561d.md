---
type: Wiki Entity
title: EphemeralUserAgentHandler
id: class:parrot.handlers.agents.ephemeral.EphemeralUserAgentHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the ephemeral user agent lifecycle.
---

# EphemeralUserAgentHandler

Defined in [`parrot.handlers.agents.ephemeral`](../summaries/mod:parrot.handlers.agents.ephemeral.md).

```python
class EphemeralUserAgentHandler(BaseView)
```

Handler for the ephemeral user agent lifecycle.

Delegates all state mutations to ``BotManager``, which is accessed via
``self.request.app['bot_manager']``.

## Methods

- `def post_init(self, *args, **kwargs) -> None` — Initialise the instance logger.
- `async def post(self) -> web.Response` — Create an ephemeral user agent (fire-and-forget warm-up).
- `async def get(self) -> web.Response` — Return the warm-up status for an ephemeral agent.
- `async def put(self) -> web.Response` — Promote an ephemeral agent to a persistent DB row.
- `async def delete(self) -> web.Response` — Discard an ephemeral agent or delete a persisted one.
