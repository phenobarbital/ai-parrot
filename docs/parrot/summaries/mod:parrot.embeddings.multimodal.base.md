---
type: Wiki Summary
title: parrot.embeddings.multimodal.base
id: mod:parrot.embeddings.multimodal.base
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multimodal Embedding Base ABC & Supporting Types.
relates_to:
- concept: class:parrot.embeddings.multimodal.base.EmbeddingBackend
  rel: defines
- concept: class:parrot.embeddings.multimodal.base.EmbeddingResult
  rel: defines
- concept: class:parrot.embeddings.multimodal.base.MultimodalEmbedding
  rel: defines
- concept: class:parrot.embeddings.multimodal.base.QuantizationMode
  rel: defines
- concept: func:parrot.embeddings.multimodal.base.resolve_image
  rel: defines
- concept: mod:parrot.embeddings.base
  rel: references
- concept: mod:parrot.embeddings.multimodal.quantization
  rel: references
---

# `parrot.embeddings.multimodal.base`

Multimodal Embedding Base ABC & Supporting Types.

Defines the abstract interface for multimodal embedding providers,
supporting both text and image inputs in a shared vector space.

## Classes

- **`EmbeddingBackend(str, Enum)`** — Runtime backend for multimodal inference.
- **`QuantizationMode(str, Enum)`** — Post-processing quantization mode for vector storage.
- **`EmbeddingResult`** — Return type for all embed_* methods.
- **`MultimodalEmbedding(EmbeddingModel)`** — Modality-aware embedding provider ABC.

## Functions

- `def resolve_image(input: ImageInput) -> 'PILImage.Image'` — Resolve an ImageInput to a PIL.Image.Image.
