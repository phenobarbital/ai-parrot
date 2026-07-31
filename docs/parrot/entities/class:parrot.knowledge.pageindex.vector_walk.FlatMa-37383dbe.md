---
type: Wiki Entity
title: FlatMatrixSearch
id: class:parrot.knowledge.pageindex.vector_walk.FlatMatrixSearch
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Brute-force cosine similarity search over a node embedding submatrix.
---

# FlatMatrixSearch

Defined in [`parrot.knowledge.pageindex.vector_walk`](../summaries/mod:parrot.knowledge.pageindex.vector_walk.md).

```python
class FlatMatrixSearch
```

Brute-force cosine similarity search over a node embedding submatrix.

Rows are L2-normalised at construction time so inner products equal
cosine similarities.

Args:
    matrix: ``(N, d)`` float32 numpy array of node embeddings.
    node_ids: List of node identifiers aligned with ``matrix`` rows.

Raises:
    ValueError: When ``len(node_ids) != matrix.shape[0]``.

## Methods

- `def search(self, query_vec: np.ndarray, top_k: int) -> list[tuple[str, float]]` — Return the top ``top_k`` nodes by cosine similarity.
