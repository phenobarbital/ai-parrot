---
type: Wiki Entity
title: ConversationTurn
id: class:parrot.memory.abstract.ConversationTurn
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents a single turn in a conversation.
---

# ConversationTurn

Defined in [`parrot.memory.abstract`](../summaries/mod:parrot.memory.abstract.md).

```python
class ConversationTurn
```

Represents a single turn in a conversation.

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Serialize turn to dictionary.
- `def from_dict(cls, data: Dict[str, Any]) -> 'ConversationTurn'` — Deserialize turn from dictionary.
