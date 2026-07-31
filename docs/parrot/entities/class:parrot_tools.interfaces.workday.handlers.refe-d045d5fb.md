---
type: Wiki Entity
title: ReferencesType
id: class:parrot_tools.interfaces.workday.handlers.references.ReferencesType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the Workday ``Get_References`` operation (Integrations service).
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# ReferencesType

Defined in [`parrot_tools.interfaces.workday.handlers.references`](../summaries/mod:parrot_tools.interfaces.workday.handlers.references.md).

```python
class ReferencesType(WorkdayTypeBase)
```

Handler for the Workday ``Get_References`` operation (Integrations service).

Returns the full catalog of instances for a given Reference_ID_Type
(e.g. ``Time_Calculation_Tag_ID``, ``Cost_Center_Reference_ID``).

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Supported parameters:
