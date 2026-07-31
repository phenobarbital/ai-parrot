---
type: Wiki Entity
title: PlanSaveResult
id: class:parrot_tools.scraping.toolkit_models.PlanSaveResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result of a plan save operation.
---

# PlanSaveResult

Defined in [`parrot_tools.scraping.toolkit_models`](../summaries/mod:parrot_tools.scraping.toolkit_models.md).

```python
class PlanSaveResult(BaseModel)
```

Result of a plan save operation.

Args:
    success: Whether the save completed successfully.
    path: Relative path where the plan file was written.
    name: Plan name.
    version: Plan version that was saved.
    registered: Whether the plan was registered in the index.
    message: Human-readable status message.
