---
type: Wiki Entity
title: BotMetadata
id: class:parrot.registry.registry.BotMetadata
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata about a discovered Bot or Agent.
---

# BotMetadata

Defined in [`parrot.registry.registry`](../summaries/mod:parrot.registry.registry.md).

```python
class BotMetadata
```

Metadata about a discovered Bot or Agent.

This class holds information about agents found during discovery,
making it easier to manage and validate them before registration.

## Methods

- `async def get_instance(self, *args, **kwargs) -> AbstractBot` — Get or create an instance of the bot.
