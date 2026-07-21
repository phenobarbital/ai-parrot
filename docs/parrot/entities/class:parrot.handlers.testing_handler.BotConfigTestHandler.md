---
type: Wiki Entity
title: BotConfigTestHandler
id: class:parrot.handlers.testing_handler.BotConfigTestHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for testing agent configurations via ephemeral sessions.
---

# BotConfigTestHandler

Defined in [`parrot.handlers.testing_handler`](../summaries/mod:parrot.handlers.testing_handler.md).

```python
class BotConfigTestHandler(BaseView)
```

Handler for testing agent configurations via ephemeral sessions.

## Methods

- `def manager(self) -> 'BotManager'` — Get BotManager from the app.
- `async def put(self) -> web.Response` — Create a test agent and store it in the user session.
- `async def post(self) -> web.Response` — Send a query to the test agent stored in the session.
- `async def delete(self) -> web.Response` — Stop the test session and remove the temporary agent.
