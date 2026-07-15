---
type: Concept
title: wire_events()
id: func:parrot.core.events.lifecycle.yaml_loader.wire_events
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Apply a parsed YAML ``events:`` block to the bot's event registry.
---

# wire_events

```python
def wire_events(bot: Any, events_block: Optional[dict]) -> None
```

Apply a parsed YAML ``events:`` block to the bot's event registry.

Iterates over ``events_block["subscribers"]`` and wires each entry as
either a handler callback (``handler:`` key) or an ``EventProvider``
subclass (``provider:`` key) onto ``bot.events``.

Args:
    bot: An ``AbstractBot`` instance that exposes ``bot.events`` (an
        ``EventRegistry``).  No-op if *bot* lacks the attribute.
    events_block: The parsed ``events:`` section from the agent YAML, or
        ``None`` / empty dict (no-op).

Raises:
    ValueError: When a subscriber entry lacks both ``handler`` and
        ``provider`` keys, or when an event class name is unknown.
    ImportError: When a dotted-path resolution fails.
