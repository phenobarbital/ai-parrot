---
type: Wiki Entity
title: QuantizationMode
id: class:parrot.embeddings.multimodal.base.QuantizationMode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Post-processing quantization mode for vector storage.
---

# QuantizationMode

Defined in [`parrot.embeddings.multimodal.base`](../summaries/mod:parrot.embeddings.multimodal.base.md).

```python
class QuantizationMode(str, Enum)
```

Post-processing quantization mode for vector storage.

Attributes:
    F32: 32-bit float (no quantization, passthrough).
    F16: 16-bit float (half precision).
    I8: 8-bit integer (maps embeddings to [-127, 127]).
    B1: 1-bit binary (sign quantization via packbits).
