---
type: Wiki Entity
title: FactoryRequest
id: class:parrot.bots.factory.contracts.FactoryRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: User-facing input to the orchestrator.
---

# FactoryRequest

Defined in [`parrot.bots.factory.contracts`](../summaries/mod:parrot.bots.factory.contracts.md).

```python
class FactoryRequest(BaseModel)
```

User-facing input to the orchestrator.

``description`` is the natural-language ask. ``clone_from`` short-circuits
the router toward the CloneBuilder. ``hints`` lets callers pin choices the
LLM would otherwise infer (useful for the HTTP handler when the caller
already knows the desired builder).
