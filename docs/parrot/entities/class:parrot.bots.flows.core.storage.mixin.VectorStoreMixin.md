---
type: Wiki Entity
title: VectorStoreMixin
id: class:parrot.bots.flows.core.storage.mixin.VectorStoreMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin to add FAISS vector store capabilities to ExecutionMemory.
---

# VectorStoreMixin

Defined in [`parrot.bots.flows.core.storage.mixin`](../summaries/mod:parrot.bots.flows.core.storage.mixin.md).

```python
class VectorStoreMixin
```

Mixin to add FAISS vector store capabilities to ExecutionMemory.

## Methods

- `def embedding_model(self)` — Return the raw (sync) embedding model for FAISS operations.
- `def embedding_model(self, value)`
- `def search_similar(self, query: str, top_k: int=5) -> List[Tuple[str, NodeResult, float]]` — Search for semantically similar result chunks.
