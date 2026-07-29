---
type: Concept
title: quantize()
id: func:parrot.embeddings.multimodal.quantization.quantize
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Apply the specified quantization to an embedding array.
---

# quantize

```python
def quantize(embeddings: np.ndarray, mode: QuantizationMode) -> np.ndarray
```

Apply the specified quantization to an embedding array.

Quantization modes:
- ``F32``: Passthrough — cast to float32 and return unchanged.
- ``F16``: Downcast to float16 (half precision).
- ``I8``: Scale by 127 and cast to int8 (range: [-127, 127]).
  Best applied to L2-normalized vectors (values in [-1, 1]).
- ``B1``: Binary quantization via ``np.packbits(embeddings > 0, axis=-1)``.
  Changes shape from (N, D) to (N, D//8). D must be divisible by 8.

Args:
    embeddings: Input embedding array. For ``I8``, should be L2-normalized
        (values in [-1, 1]) for correct range. For ``B1``, last dimension
        must be divisible by 8.
    mode: Target quantization mode.

Returns:
    Quantized array. Shape is unchanged except for ``B1`` which compresses
    the last dimension by factor 8.
