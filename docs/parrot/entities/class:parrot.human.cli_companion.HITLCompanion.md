---
type: Wiki Entity
title: HITLCompanion
id: class:parrot.human.cli_companion.HITLCompanion
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interactive CLI companion for the HITL daemon channel.
---

# HITLCompanion

Defined in [`parrot.human.cli_companion`](../summaries/mod:parrot.human.cli_companion.md).

```python
class HITLCompanion
```

Interactive CLI companion for the HITL daemon channel.

Connects to Redis, pulls pending interactions, and lets
the human respond through a Rich-formatted terminal UI.

The companion is designed to run alongside (or separately from)
the agent process. Multiple companions can run for different
users simultaneously.

## Methods

- `async def run(self) -> None` — Main loop: process pending + listen for new interactions.
- `async def shutdown(self) -> None` — Clean shutdown.
