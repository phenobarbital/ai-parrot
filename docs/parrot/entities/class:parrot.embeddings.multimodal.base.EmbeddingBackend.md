---
type: Wiki Entity
title: EmbeddingBackend
id: class:parrot.embeddings.multimodal.base.EmbeddingBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Runtime backend for multimodal inference.
---

# EmbeddingBackend

Defined in [`parrot.embeddings.multimodal.base`](../summaries/mod:parrot.embeddings.multimodal.base.md).

```python
class EmbeddingBackend(str, Enum)
```

Runtime backend for multimodal inference.

Attributes:
    TORCH: PyTorch backend (full precision, dev/GPU usage).
    ONNX: ONNX Runtime backend (lightweight, Knative serving).
