---
type: Wiki Entity
title: UFormEmbedding
id: class:parrot.embeddings.multimodal.uform.UFormEmbedding
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: UForm-backed multimodal embedding provider.
relates_to:
- concept: class:parrot.embeddings.multimodal.base.MultimodalEmbedding
  rel: extends
---

# UFormEmbedding

Defined in [`parrot.embeddings.multimodal.uform`](../summaries/mod:parrot.embeddings.multimodal.uform.md).

```python
class UFormEmbedding(MultimodalEmbedding)
```

UForm-backed multimodal embedding provider.

Wraps UForm's CLIP-style text and image encoders with dual backend
support:
- ``torch``: Full PyTorch model (~206 MB for multilingual-base).
  Preferred for dev and GPU inference.
- ``onnx``: ONNX Runtime session (~100-300 MB). Preferred for Knative
  CPU serving with low memory footprint.

Both backends produce embeddings in the same shared vector space for a
given model, enabling cross-modal retrieval. All outputs are
L2-normalized via :meth:`_postprocess`.

Args:
    model_name: HuggingFace model identifier. Defaults to the
        multilingual-base model which supports 21 languages.
    backend: Runtime backend (torch or ONNX). Default: torch.
    output_dim: Matryoshka truncation dimension. ``None`` = full model dim.
    quantization: Post-processing quantization mode. Default: F32.
    device: Device string passed to UForm (``"cpu"`` or ``"cuda"``).
    **kwargs: Extra keyword arguments forwarded to :class:`EmbeddingModel`.

## Methods

- `async def initialize_model(self) -> None` — Async model initialization — loads UForm in a thread executor.
- `async def encode(self, texts: List[str], **kwargs) -> np.ndarray` — Encode a batch of texts to embeddings (async, non-blocking).
- `async def embed_text(self, texts: List[str]) -> EmbeddingResult` — Embed a batch of text strings.
- `async def embed_images(self, images: List[ImageInput]) -> EmbeddingResult` — Embed a batch of images.
- `def free(self) -> None` — Release model resources and clear caches.
