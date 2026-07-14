---
type: Concept
title: postprocess()
id: func:parrot.embeddings.multimodal.quantization.postprocess
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Apply the full post-processing pipeline: slice -> normalize -> quantize.'
---

# postprocess

```python
def postprocess(embeddings: np.ndarray, output_dim: int | None, mode: QuantizationMode) -> np.ndarray
```

Apply the full post-processing pipeline: slice -> normalize -> quantize.

Processing order:
1. Matryoshka slice to ``output_dim`` leading dims (skipped if ``None``).
2. L2 renormalization (always applied; makes cosine == dot).
3. Quantization per ``mode``.

Args:
    embeddings: Raw embedding array of shape (N, D).
    output_dim: Matryoshka truncation dim. ``None`` skips slicing.
    mode: Quantization mode to apply.

Returns:
    Processed embedding array.
