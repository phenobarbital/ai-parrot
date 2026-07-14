---
type: Wiki Entity
title: MSTeamsCommandRouter
id: class:parrot.integrations.msteams.commands.MSTeamsCommandRouter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Detects and routes text commands in ``on_message_activity``.
---

# MSTeamsCommandRouter

Defined in [`parrot.integrations.msteams.commands`](../summaries/mod:parrot.integrations.msteams.commands.md).

```python
class MSTeamsCommandRouter
```

Detects and routes text commands in ``on_message_activity``.

A *command* is a message whose first word starts with ``/``.  The router
strips the leading slash, looks up the normalized name in the handler
registry, and calls the matching handler.

Non-command text (no leading ``/``) returns ``False`` without touching
the registered handlers, so the caller can continue to normal agent
processing.

Example::

    router = MSTeamsCommandRouter()
    router.register("connect_jira", my_handler)

    handled = await router.try_dispatch("/connect_jira", turn_context)
    assert handled is True

Attributes:
    _handlers: Mapping from normalized command name to handler callable.

## Methods

- `def register(self, command: str, handler: Callable) -> None` — Register a handler for *command*.
- `async def try_dispatch(self, text: str, turn_context: 'TurnContext') -> bool` — Attempt to dispatch *text* as a slash command.
- `async def try_dispatch_plain(self, text: str, turn_context: 'TurnContext') -> bool` — Attempt to dispatch *text* as a plain-text (non-slash) trigger.
- `def registered_commands(self) -> list[str]` — Return the list of registered command names (without ``/``).
