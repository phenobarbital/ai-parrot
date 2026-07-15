---
type: Wiki Summary
title: parrot.embeddings.multimodal.quantization
id: mod:parrot.embeddings.multimodal.quantization
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Quantization and Matryoshka post-processing utilities.
relates_to:
- concept: func:parrot.embeddings.multimodal.quantization.l2_normalize
  rel: defines
- concept: func:parrot.embeddings.multimodal.quantization.matryoshka_slice
  rel: defines
- concept: func:parrot.embeddings.multimodal.quantization.postprocess
  rel: defines
- concept: func:parrot.embeddings.multimodal.quantization.quantize
  rel: defines
- concept: mod:parrot.embeddings.multimodal.base
  rel: references
---

# `parrot.embeddings.multimodal.quantization`

Quantization and Matryoshka post-processing utilities.

Provides shared model-agnostic post-processing for multimodal embeddings:
- Matryoshka dimension slicing (leading N dims)
- L2 renormalization
- Quantization (f32/f16/i8/b1)
- PgVector column type mapping

All functions are pure (no side effects, no state).

## Functions

- `def matryoshka_slice(embeddings: np.ndarray, dim: int) -> np.ndarray` — Slice the leading ``dim`` dimensions from each embedding vector.
- `def l2_normalize(embeddings: np.ndarray) -> np.ndarray` — L2-normalize each row vector to unit length.
- `def quantize(embeddings: np.ndarray, mode: QuantizationMode) -> np.ndarray` — Apply the specified quantization to an embedding array.
- `def postprocess(embeddings: np.ndarray, output_dim: int | None, mode: QuantizationMode) -> np.ndarray` — Apply the full post-processing pipeline: slice -> normalize -> quantize.
