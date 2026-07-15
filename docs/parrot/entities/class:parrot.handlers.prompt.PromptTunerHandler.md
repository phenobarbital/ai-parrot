---
type: Wiki Entity
title: PromptTunerHandler
id: class:parrot.handlers.prompt.PromptTunerHandler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runtime system-prompt fine-tuning console.
---

# PromptTunerHandler

Defined in [`parrot.handlers.prompt`](../summaries/mod:parrot.handlers.prompt.md).

```python
class PromptTunerHandler(BaseView)
```

Runtime system-prompt fine-tuning console.

Delegates instance lookup/cloning to ``BotManager`` (``app['bot_manager']``)
and keeps per-user edits in the session so concurrent editors never collide.

## Methods

- `def manager(self) -> Optional['BotManager']` — Return the BotManager attached to the app, if any.
- `async def get(self) -> web.Response` — Return the agent's current prompt parts, rendered prompt, and draft.
- `async def patch(self) -> web.Response` — Merge ``{fields:{...}, layers:{...}}`` into the session draft.
- `async def post(self) -> web.Response` — Dispatch on the trailing path segment: suggest | test | save.
- `async def delete(self) -> web.Response` — Discard the session draft and any ephemeral test clone.
