---
type: Wiki Entity
title: ToolCallFailedEvent
id: class:parrot.core.events.lifecycle.events.tool.ToolCallFailedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when AbstractTool._execute() raises an exception.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# ToolCallFailedEvent

Defined in [`parrot.core.events.lifecycle.events.tool`](../summaries/mod:parrot.core.events.lifecycle.events.tool.md).

```python
class ToolCallFailedEvent(LifecycleEvent)
```

Emitted when AbstractTool._execute() raises an exception.

AfterToolCallEvent is NOT emitted when this fires.

Attributes:
    tool_name: Name of the tool that was called.
    duration_ms: Wall-clock time in milliseconds until failure.
    error_type: ``type(exc).__name__`` of the exception.
    error_message: String representation of the exception.
