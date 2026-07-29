---
type: Wiki Entity
title: EmbeddingResult
id: class:parrot.embeddings.multimodal.base.EmbeddingResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return type for all embed_* methods.
---

# EmbeddingResult

Defined in [`parrot.embeddings.multimodal.base`](../summaries/mod:parrot.embeddings.multimodal.base.md).

```python
class EmbeddingResult
```

Return type for all embed_* methods.

Attributes:
    embeddings: Embedding matrix of shape (N, dim).
    dimension: Post-Matryoshka output dimension.
    quantization: The quantization mode applied.
    modality: Source modality: "text", "image", or "mixed".
