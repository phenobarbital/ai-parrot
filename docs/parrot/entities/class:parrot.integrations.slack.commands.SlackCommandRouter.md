---
type: Wiki Entity
title: SlackCommandRouter
id: class:parrot.integrations.slack.commands.SlackCommandRouter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Routes slash commands to registered async handler functions.
---

# SlackCommandRouter

Defined in [`parrot.integrations.slack.commands`](../summaries/mod:parrot.integrations.slack.commands.md).

```python
class SlackCommandRouter
```

Routes slash commands to registered async handler functions.

Each command is registered under a normalized name (the text that
follows the slash, without the ``/`` prefix, e.g. ``"connect_jira"``).
``dispatch`` looks up the handler and calls it with the slash-command
payload dict.  If no handler is registered for the command, it returns
``None`` so the caller can fall through to the next handler.

Example::

    router = SlackCommandRouter()
    router.register("ping", my_ping_handler)
    result = await router.dispatch("ping", payload)
    # result is the return value of my_ping_handler, or None

Attributes:
    _handlers: Mapping from normalized command name to handler callable.

## Methods

- `def register(self, command: str, handler: Callable) -> None` — Register a handler for *command*.
- `async def dispatch(self, command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]` — Dispatch *command* to its registered handler.
- `def registered_commands(self) -> list[str]` — Return the list of registered command names (without ``/``).
