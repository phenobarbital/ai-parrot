---
type: Concept
title: serialize_task_state()
id: func:parrot.a2a.models.serialize_task_state
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Serialize a TaskState to the wire value for the target protocol version.
---

# serialize_task_state

```python
def serialize_task_state(state: 'TaskState', version: str='1.0') -> str
```

Serialize a TaskState to the wire value for the target protocol version.
