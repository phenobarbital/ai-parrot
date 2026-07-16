---
type: Wiki Entity
title: ProductAdvisorToolArgs
id: class:parrot.advisors.tools.base.ProductAdvisorToolArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base args schema with common fields for advisor tools.
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# ProductAdvisorToolArgs

Defined in [`parrot.advisors.tools.base`](../summaries/mod:parrot.advisors.tools.base.md).

```python
class ProductAdvisorToolArgs(AbstractToolArgsSchema)
```

Base args schema with common fields for advisor tools.

``user_id`` and ``session_id`` are injected by the framework at
execution time — the LLM never sees them in the tool schema.
