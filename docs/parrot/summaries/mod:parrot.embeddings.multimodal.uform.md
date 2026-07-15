---
type: Wiki Summary
title: parrot.embeddings.multimodal.uform
id: mod:parrot.embeddings.multimodal.uform
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UForm Embedding Provider.
relates_to:
- concept: class:parrot.embeddings.multimodal.uform.UFormEmbedding
  rel: defines
- concept: mod:parrot.embeddings.multimodal.base
  rel: references
---

# `parrot.embeddings.multimodal.uform`

UForm Embedding Provider.

Implements the ``UFormEmbedding`` concrete class using UForm's CLIP-style
encoders. Supports both PyTorch and ONNX backends for dev/GPU vs Knative
serving footprints respectively.

UForm returns text and image embeddings in the same shared vector space,
enabling cross-modal retrieval (text<->image) in PgVector.

External dependency: ``uform>=3.1`` (install with ``uform[torch]`` for GPU).

## Classes

- **`UFormEmbedding(MultimodalEmbedding)`** — UForm-backed multimodal embedding provider.
