---
type: Wiki Entity
title: ChannelRegistry
id: class:parrot.human.channels.ChannelRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry for HumanChannel implementations.
---

# ChannelRegistry

Defined in [`parrot.human.channels`](../summaries/mod:parrot.human.channels.md).

```python
class ChannelRegistry
```

Registry for HumanChannel implementations.

Satellite packages (e.g. ai-parrot-integrations) register channel
implementations at module import time so that the core can discover
them without a static dependency::

    # packages/ai-parrot-integrations/src/parrot/human/channels/telegram.py
    from parrot.human.channels import ChannelRegistry
    ChannelRegistry.register("telegram", TelegramHumanChannel)

The registry works gracefully when *no* channels are registered
(e.g. when only the core package is installed).

## Methods

- `def register(cls, name: str, channel_cls: type) -> None` — Register a channel implementation under ``name``.
- `def get(cls, name: str) -> type | None` — Return the registered channel class for ``name``, or ``None``.
- `def available(cls) -> list[str]` — Return a list of registered channel names.
