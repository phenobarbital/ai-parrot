---
type: Wiki Entity
title: WorkdayCostCenterMapping
id: class:parrot_formdesigner.services.project_service.WorkdayCostCenterMapping
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mapping from an internal project to a Workday cost center code.
---

# WorkdayCostCenterMapping

Defined in [`parrot_formdesigner.services.project_service`](../summaries/mod:parrot_formdesigner.services.project_service.md).

```python
class WorkdayCostCenterMapping(BaseModel)
```

Mapping from an internal project to a Workday cost center code.

Attributes:
    project_id: FK to ``fieldsync.projects``.
    workday_code: Workday cost center identifier (output side only).
    direction: Flow direction; default is ``"internal_to_workday"``.
