---
type: Wiki Entity
title: SynthesisMixin
id: class:parrot.bots.flows.core.storage.synthesis.SynthesisMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin that adds LLM-based result synthesis to crew/flow orchestrators.
---

# SynthesisMixin

Defined in [`parrot.bots.flows.core.storage.synthesis`](../summaries/mod:parrot.bots.flows.core.storage.synthesis.md).

```python
class SynthesisMixin
```

Mixin that adds LLM-based result synthesis to crew/flow orchestrators.

Requires the host class to have a ``logger`` attribute.
The ``llm`` client is passed explicitly to avoid hard-coupling to a
specific ``self._llm`` attribute.
