---
type: Wiki Entity
title: VectorInterface
id: class:parrot.interfaces.vector.VectorInterface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Interface for vector store management and search operations.
---

# VectorInterface

Defined in [`parrot.interfaces.vector`](../summaries/mod:parrot.interfaces.vector.md).

```python
class VectorInterface
```

Interface for vector store management and search operations.

This interface provides methods for:
- Configuring and managing vector stores
- Performing ensemble searches (similarity + MMR)
- Combining and reranking search results
- Reciprocal rank fusion

## Methods

- `def configure_store(self, **kwargs)` — Configure Vector Store.
- `def define_store(self, vector_store: str='postgres', **kwargs)` — Define the Vector Store.
