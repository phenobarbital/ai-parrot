---
type: Wiki Entity
title: VectorStoreProtocol
id: class:parrot.models.crew.VectorStoreProtocol
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol for vector store implementations
---

# VectorStoreProtocol

Defined in [`parrot.models.crew`](../summaries/mod:parrot.models.crew.md).

```python
class VectorStoreProtocol(Protocol)
```

Protocol for vector store implementations

## Methods

- `def encode(self, texts: List[str]) -> np.ndarray` — Encode texts to embeddings
