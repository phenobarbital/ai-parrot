---
type: Wiki Entity
title: TurnRecord
id: class:parrot.eval.models.TurnRecord
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single conversational turn in a trajectory.
---

# TurnRecord

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class TurnRecord(BaseModel)
```

A single conversational turn in a trajectory.

Attributes:
    role: Speaker role — ``"user"``, ``"agent"``, ``"tool"``, or
        ``"system"``.
    content: Text content of the turn (may be ``None`` for tool-only
        turns).
    tool_calls: Tool invocations that occurred during this turn.
    timestamp: Unix epoch timestamp when this turn was recorded.
