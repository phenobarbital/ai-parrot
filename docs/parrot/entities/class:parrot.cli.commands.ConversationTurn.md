---
type: Wiki Entity
title: ConversationTurn
id: class:parrot.cli.commands.ConversationTurn
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single turn in the conversation history (used by ``/export``).
---

# ConversationTurn

Defined in [`parrot.cli.commands`](../summaries/mod:parrot.cli.commands.md).

```python
class ConversationTurn
```

A single turn in the conversation history (used by ``/export``).

Attributes:
    query: The user's input.
    response: The agent's ``AIMessage`` response.
    timestamp: When this turn occurred.

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Serialise the turn to a JSON-safe dictionary.
