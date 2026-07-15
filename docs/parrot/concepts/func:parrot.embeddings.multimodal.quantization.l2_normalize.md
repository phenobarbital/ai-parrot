---
type: Concept
title: l2_normalize()
id: func:parrot.embeddings.multimodal.quantization.l2_normalize
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: L2-normalize each row vector to unit length.
---

# l2_normalize

```python
def l2_normalize(embeddings: np.ndarray) -> np.ndarray
```

L2-normalize each row vector to unit length.

Zero vectors are left unchanged (their norm is treated as 1.0) to avoid
NaN values.

Args:
    embeddings: Float array of shape (N, D) or (D,).

Returns:
    Array of the same shape and dtype with each vector having norm == 1.0.
    Zero vectors are returned unchanged.
