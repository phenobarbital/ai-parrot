---
type: Wiki Entity
title: PulumiPlanInput
id: class:parrot_tools.pulumi.config.PulumiPlanInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for pulumi_plan operation.
---

# PulumiPlanInput

Defined in [`parrot_tools.pulumi.config`](../summaries/mod:parrot_tools.pulumi.config.md).

```python
class PulumiPlanInput(BaseModel)
```

Input for pulumi_plan operation.

Used to preview infrastructure changes without applying them.
Returns a detailed diff of resources to be created, updated, or deleted.
