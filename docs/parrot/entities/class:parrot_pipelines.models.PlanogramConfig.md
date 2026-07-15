---
type: Wiki Entity
title: PlanogramConfig
id: class:parrot_pipelines.models.PlanogramConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Complete configuration for planogram analysis pipeline.
---

# PlanogramConfig

Defined in [`parrot_pipelines.models`](../summaries/mod:parrot_pipelines.models.md).

```python
class PlanogramConfig(BaseModel)
```

Complete configuration for planogram analysis pipeline.
Contains planogram description, prompts, and reference images.

## Methods

- `def get_planogram_description(self) -> PlanogramDescription` — Load and validate a planogram description from a configuration dictionary.
