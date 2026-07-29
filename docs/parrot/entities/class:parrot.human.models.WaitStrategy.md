---
type: Wiki Entity
title: WaitStrategy
id: class:parrot.human.models.WaitStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Strategy that controls how HumanTool waits for the human response.
---

# WaitStrategy

Defined in [`parrot.human.models`](../summaries/mod:parrot.human.models.md).

```python
class WaitStrategy(str, Enum)
```

Strategy that controls how HumanTool waits for the human response.

Attributes:
    BLOCK: Default — registers an in-memory asyncio.Future and blocks
        the current coroutine until the human responds (or timeout).
        Suitable for live-channel deployments (Telegram, WebSocket long-poll).
    SUSPEND: Stateless web path — persists the interaction to Redis and
        raises HumanInteractionInterrupt immediately, allowing the HTTP
        handler to serialise tool-loop state and return a ``paused``
        envelope.  No in-process timer is relied upon.
    HOT_THEN_SUSPEND: Reserved for future live-channel + REST hybrid use.
        Currently treated the same as BLOCK.
