---
type: Wiki Entity
title: WorkdayTypeBase
id: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Workday operation types.
---

# WorkdayTypeBase

Defined in [`parrot_tools.interfaces.workday.handlers.base`](../summaries/mod:parrot_tools.interfaces.workday.handlers.base.md).

```python
class WorkdayTypeBase(ABC)
```

Base class for Workday operation types.

Provides:
  - Default payload structure for all Workday operations.
  - Generic pagination logic with retries and logging.
  - Common SOAP response handling utilities.

## Methods

- `async def execute(self, **kwargs) -> Any` — Execute the specific operation logic.
