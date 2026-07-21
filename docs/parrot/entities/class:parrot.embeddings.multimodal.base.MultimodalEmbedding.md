---
type: Wiki Entity
title: MultimodalEmbedding
id: class:parrot.embeddings.multimodal.base.MultimodalEmbedding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Modality-aware embedding provider ABC.
relates_to:
- concept: class:parrot.embeddings.base.EmbeddingModel
  rel: extends
---

# MultimodalEmbedding

Defined in [`parrot.embeddings.multimodal.base`](../summaries/mod:parrot.embeddings.multimodal.base.md).

```python
class MultimodalEmbedding(EmbeddingModel)
```

Modality-aware embedding provider ABC.

Extends :class:`EmbeddingModel` with image support and shared-space
guarantees. Concrete providers (e.g. UFormEmbedding) inherit from this
class and implement :meth:`embed_text`, :meth:`embed_images`,
:meth:`_create_embedding`, and :meth:`encode`.

All outputs are L2-normalized so cosine similarity equals dot product.
Text and image embeddings share the same dimension for a given model,
enabling cross-modal retrieval in PgVector.

Args:
    model_name: Provider model identifier.
    output_dim: Matryoshka truncation dimension. None = full model dim.
    quantization: Post-processing quantization mode (default F32).
    **kwargs: Extra arguments forwarded to :class:`EmbeddingModel`.

## Methods

- `async def embed_text(self, texts: List[str]) -> EmbeddingResult` — Embed a batch of text strings.
- `async def embed_images(self, images: List[ImageInput]) -> EmbeddingResult` — Embed a batch of images.
- `async def embed_documents(self, docs: List, batch_size: Optional[int]=None) -> EmbeddingResult` — Route documents by modality to embed_text or embed_images.
