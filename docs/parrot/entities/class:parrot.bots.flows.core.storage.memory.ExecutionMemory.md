---
type: Wiki Entity
title: ExecutionMemory
id: class:parrot.bots.flows.core.storage.memory.ExecutionMemory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory storage for execution history.
relates_to:
- concept: class:parrot.bots.flows.core.storage.mixin.VectorStoreMixin
  rel: extends
---

# ExecutionMemory

Defined in [`parrot.bots.flows.core.storage.memory`](../summaries/mod:parrot.bots.flows.core.storage.memory.md).

```python
class ExecutionMemory(VectorStoreMixin)
```

In-memory storage for execution history.

Optionally indexes results into a FAISS vector store (via
``VectorStoreMixin``) when an ``embedding_model`` is provided.

Args:
    original_query: The initial prompt/task string for this execution.
    embedding_model: Optional embedding model for FAISS indexing.
    dimension: Embedding dimension (default 384).
    index_type: FAISS index type (``"Flat"``, ``"FlatIP"``, or ``"HNSW"``).

## Methods

- `def add_result(self, result: NodeResult, vectorize: bool=True) -> None` — Add a result and update execution graph.
- `def get_results_by_agent(self, agent_id: str) -> Optional[NodeResult]` — Retrieve result from a specific agent/node.
- `def get_reexecuted_results(self) -> List[NodeResult]` — Return only results from re-executions triggered by ``ask()``.
- `def get_context_for_agent(self, agent_id: str) -> Any` — Return the context available to an agent at execution time.
- `def clear(self, keep_query: bool=False) -> None` — Clear execution memory.
- `def get_snapshot(self) -> Dict[str, Any]` — Return a serialisable snapshot of the current memory state.
