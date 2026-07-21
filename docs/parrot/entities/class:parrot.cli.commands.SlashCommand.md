---
type: Wiki Entity
title: SlashCommand
id: class:parrot.cli.commands.SlashCommand
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A registered slash command.
---

# SlashCommand

Defined in [`parrot.cli.commands`](../summaries/mod:parrot.cli.commands.md).

```python
class SlashCommand
```

A registered slash command.

Attributes:
    name: Command trigger string (without leading slash), e.g. ``tools``.
    description: Short description shown in ``/help``.
    handler: Async callable ``handler(repl, args) -> None``.
