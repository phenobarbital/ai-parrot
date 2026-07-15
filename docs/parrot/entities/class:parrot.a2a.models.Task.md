---
type: Wiki Entity
title: Task
id: class:parrot.a2a.models.Task
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unit of work with lifecycle.
---

# Task

Defined in [`parrot.a2a.models`](../summaries/mod:parrot.a2a.models.md).

```python
class Task
```

Unit of work with lifecycle.

## Methods

- `def create(cls, context_id: Optional[str]=None) -> 'Task'`
- `def working(self, message: Optional[str]=None) -> 'Task'`
- `def complete(self, response: Any) -> 'Task'`
- `def fail(self, error: str) -> 'Task'`
- `def to_dict(self, version: str='1.0') -> Dict[str, Any]`
