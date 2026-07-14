---
type: Wiki Entity
title: AfterToolCallEvent
id: class:parrot.core.events.lifecycle.events.tool.AfterToolCallEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted after AbstractTool._execute() completes successfully.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AfterToolCallEvent

Defined in [`parrot.core.events.lifecycle.events.tool`](../summaries/mod:parrot.core.events.lifecycle.events.tool.md).

```python
class AfterToolCallEvent(LifecycleEvent)
```

Emitted after AbstractTool._execute() completes successfully.

NOT emitted when _execute() raises (ToolCallFailedEvent is used instead).

Attributes:
    tool_name: Name of the tool that was called.
    duration_ms: Wall-clock time in milliseconds.
    result_status: ``"success"`` or ``"partial"`` based on the ToolResult.
    result_size_bytes: UTF-8 encoded byte length of the serialized result.
