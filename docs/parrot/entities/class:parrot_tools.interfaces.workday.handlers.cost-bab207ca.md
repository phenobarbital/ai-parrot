---
type: Wiki Entity
title: CostCenterType
id: class:parrot_tools.interfaces.workday.handlers.cost_centers.CostCenterType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handler for the Workday Get_Cost_Centers operation.
relates_to:
- concept: class:parrot_tools.interfaces.workday.handlers.base.WorkdayTypeBase
  rel: extends
---

# CostCenterType

Defined in [`parrot_tools.interfaces.workday.handlers.cost_centers`](../summaries/mod:parrot_tools.interfaces.workday.handlers.cost_centers.md).

```python
class CostCenterType(WorkdayTypeBase)
```

Handler for the Workday Get_Cost_Centers operation.

## Methods

- `async def execute(self, **kwargs) -> pd.DataFrame` — Execute the Get_Cost_Centers operation and return a pandas DataFrame.
