---
type: Wiki Entity
title: ProducerResult
id: class:parrot.outputs.a2ui.producer.ProducerResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Outcome of :func:`generate_envelope`.
---

# ProducerResult

Defined in [`parrot.outputs.a2ui.producer`](../summaries/mod:parrot.outputs.a2ui.producer.md).

```python
class ProducerResult(BaseModel)
```

Outcome of :func:`generate_envelope`.

On success ``envelope`` is set and ``degraded`` is ``False``. On failure the invalid
envelope is discarded (G1) and ``text`` carries the plain-text degradation.

Attributes:
    envelope: The validated ``CreateSurface`` (``None`` when degraded).
    text: Plain-text degradation (``None`` on success).
    degraded: Whether the producer fell back to text.
    failure_reason: Machine-readable reason when degraded.
    attempts: Number of ``ask()`` attempts made.
