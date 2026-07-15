---
type: Wiki Entity
title: PulumiApplyInput
id: class:parrot_tools.pulumi.config.PulumiApplyInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for pulumi_apply operation.
---

# PulumiApplyInput

Defined in [`parrot_tools.pulumi.config`](../summaries/mod:parrot_tools.pulumi.config.md).

```python
class PulumiApplyInput(BaseModel)
```

Input for pulumi_apply operation.

Used to apply infrastructure changes. By default runs with auto_approve=True
to avoid interactive prompts in agent workflows.
