---
type: Wiki Entity
title: TaskState
id: class:parrot.a2a.models.TaskState
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Task lifecycle states — v1.0.0 ProtoJSON values.
---

# TaskState

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class TaskState(str, Enum)
```

Task lifecycle states — v1.0.0 ProtoJSON values.

The canonical member value is the v1.0 ``TASK_STATE_*`` string. The legacy
v0.3 lowercase values (``"submitted"`` …) are handled by
:func:`parse_task_state` on deserialization and :func:`serialize_task_state`
on serialization.
