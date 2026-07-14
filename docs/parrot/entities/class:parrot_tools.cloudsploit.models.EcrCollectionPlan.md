---
type: Wiki Entity
title: EcrCollectionPlan
id: class:parrot_tools.cloudsploit.models.EcrCollectionPlan
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Plan for ``collect_ecr_findings``. Loaded from a YAML file at runtime.
---

# EcrCollectionPlan

Defined in [`parrot_tools.cloudsploit.models`](../summaries/mod:parrot_tools.cloudsploit.models.md).

```python
class EcrCollectionPlan(BaseModel)
```

Plan for ``collect_ecr_findings``.  Loaded from a YAML file at runtime.

## Methods

- `def from_yaml(cls, path: Union[str, 'Path']) -> 'EcrCollectionPlan'` — Load and validate a plan from a YAML file.
