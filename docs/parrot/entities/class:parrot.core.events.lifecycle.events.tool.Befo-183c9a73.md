---
type: Wiki Entity
title: BeforeToolCallEvent
id: class:parrot.core.events.lifecycle.events.tool.BeforeToolCallEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted just before AbstractTool._execute() is called.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# BeforeToolCallEvent

Defined in [`parrot.core.events.lifecycle.events.tool`](../summaries/mod:parrot.core.events.lifecycle.events.tool.md).

```python
class BeforeToolCallEvent(LifecycleEvent)
```

Emitted just before AbstractTool._execute() is called.

Attributes:
    tool_name: Name of the tool being called.
    tool_class: Fully-qualified class name of the concrete tool.
    args_summary: Truncated, JSON-safe dict of call arguments.
        Strings are truncated at 200 chars; binary/non-primitive values
        are replaced with type descriptors. Hashing happens at the
        emission site (AbstractTool.execute), not here.
