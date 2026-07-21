---
type: Wiki Entity
title: PulumiDestroyInput
id: class:parrot_tools.pulumi.config.PulumiDestroyInput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Input for pulumi_destroy operation.
---

# PulumiDestroyInput

Defined in [`parrot_tools.pulumi.config`](../summaries/mod:parrot_tools.pulumi.config.md).

```python
class PulumiDestroyInput(BaseModel)
```

Input for pulumi_destroy operation.

Used to tear down infrastructure. By default runs with auto_approve=True
to avoid interactive prompts in agent workflows.
