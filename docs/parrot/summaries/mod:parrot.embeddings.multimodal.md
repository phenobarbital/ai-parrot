---
type: Wiki Summary
title: parrot.embeddings.multimodal
id: mod:parrot.embeddings.multimodal
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multimodal Embedding Provider package.
relates_to:
- concept: mod:parrot.embeddings
  rel: references
- concept: mod:parrot.embeddings.base
  rel: references
---

# `parrot.embeddings.multimodal`

Multimodal Embedding Provider package.

Exports the public API for multimodal (text + image) embedding providers,
enums, result types, image utilities, and quantization helpers.

Usage:
    from parrot.embeddings.multimodal import (
        MultimodalEmbedding,
        EmbeddingResult,
        EmbeddingBackend,
        QuantizationMode,
        ImageInput,
        resolve_image,
    )
    from parrot.embeddings.multimodal.quantization import (
        matryoshka_slice, l2_normalize, quantize, PGVECTOR_TYPE_MAP,
    )
