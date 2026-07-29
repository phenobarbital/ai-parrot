---
type: Wiki Entity
title: EnvState
id: class:parrot_tools.computer.models.EnvState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: State returned after each computer-use action.
---

# EnvState

Defined in [`parrot_tools.computer.models`](../summaries/mod:parrot_tools.computer.models.md).

```python
class EnvState(BaseModel)
```

State returned after each computer-use action.

Every action executed by the AsyncComputerBackend captures a
screenshot and the current URL, returning them as an EnvState.

Attributes:
    screenshot: Raw PNG bytes of the current viewport.
    url: The current page URL after the action.
