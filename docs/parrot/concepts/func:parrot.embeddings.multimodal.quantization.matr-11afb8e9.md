---
type: Concept
title: matryoshka_slice()
id: func:parrot.embeddings.multimodal.quantization.matryoshka_slice
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Slice the leading ``dim`` dimensions from each embedding vector.
---

# matryoshka_slice

```python
def matryoshka_slice(embeddings: np.ndarray, dim: int) -> np.ndarray
```

Slice the leading ``dim`` dimensions from each embedding vector.

This implements the Matryoshka truncation: the first N dimensions of a
Matryoshka-trained embedding already form a high-quality sub-embedding,
so slicing is lossless in the Matryoshka sense.

Args:
    embeddings: Float array of shape (N, D) or (D,).
    dim: Number of leading dimensions to keep. Must satisfy 1 <= dim <= D.

Returns:
    Array of shape (N, dim) or (dim,) with the same dtype as input.
