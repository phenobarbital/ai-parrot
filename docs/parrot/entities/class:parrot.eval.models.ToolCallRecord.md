---
type: Wiki Entity
title: ToolCallRecord
id: class:parrot.eval.models.ToolCallRecord
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Record of a single tool invocation during a trajectory turn.
---

# ToolCallRecord

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class ToolCallRecord(BaseModel)
```

Record of a single tool invocation during a trajectory turn.

Attributes:
    name: Tool name called.
    arguments: Arguments passed to the tool.
    result: Return value of the tool, if available.
    error: Error string if the tool raised, otherwise ``None``.
    latency_ms: Wall-clock time for the tool call in milliseconds.
