---
type: Wiki Summary
title: parrot.rerankers.local
id: mod:parrot.rerankers.local
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local cross-encoder reranker implementation.
relates_to:
- concept: class:parrot.rerankers.local.LocalCrossEncoderReranker
  rel: defines
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.rerankers.abstract
  rel: references
- concept: mod:parrot.rerankers.models
  rel: references
---

# `parrot.rerankers.local`

Local cross-encoder reranker implementation.

This module provides ``LocalCrossEncoderReranker``, a production-grade
in-process reranker that loads a HuggingFace cross-encoder model once and
scores ``(query, passage)`` pairs via batched forward passes.

Supported models:

- ``BAAI/bge-reranker-v2-m3`` (default, 568M params, multilingual)
- ``jinaai/jina-reranker-v2-base-multilingual`` (278M, requires
  ``trust_remote_code=True``)
- ``cross-encoder/ms-marco-MiniLM-L-12-v2`` (33M, English-only, fast CI path)

Device/precision autodetection:

- GPU available → FP16 (``model.half()``)
- CPU only → INT8 (``torch.quantization.quantize_dynamic`` on ``nn.Linear``)
- Override via ``RerankerConfig.device`` / ``RerankerConfig.precision``

Raises:
    ImportError: At module import time if ``transformers`` or ``torch`` are
        not installed.

## Classes

- **`LocalCrossEncoderReranker(AbstractReranker)`** — In-process cross-encoder reranker using HuggingFace models.
