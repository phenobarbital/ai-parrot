---
type: Wiki Entity
title: RerankerConfig
id: class:parrot.rerankers.models.RerankerConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Construction configuration for LocalCrossEncoderReranker.
---

# RerankerConfig

Defined in [`parrot.rerankers.models`](../summaries/mod:parrot.rerankers.models.md).

```python
class RerankerConfig(BaseModel)
```

Construction configuration for LocalCrossEncoderReranker.

Attributes:
    model_name: HuggingFace model ID to load.
        Default: ``"BAAI/bge-reranker-v2-m3"`` (production, multilingual).
        Alternatives:
        - ``"jinaai/jina-reranker-v2-base-multilingual"`` (requires
          ``trust_remote_code=True``).
        - ``"cross-encoder/ms-marco-MiniLM-L-12-v2"`` (dev/CI fast path).
    device: Target device. ``"auto"`` resolves to ``"cuda"`` if a GPU is
        available, otherwise ``"cpu"``.
    precision: Numeric precision. ``"auto"`` resolves to FP16 on CUDA and
        INT8 (PyTorch dynamic quantization) on CPU. Explicit values:
        ``"fp32"``, ``"fp16"``, ``"int8"``.
    max_length: Maximum token length for tokenisation. Inputs longer than
        this value are truncated.
    batch_size: Number of ``(query, passage)`` pairs processed per forward
        pass when the document list exceeds this value.
    trust_remote_code: Required ``True`` for Jina v2 models that use a
        custom HuggingFace architecture class. Default ``False`` for security.
    warmup: When ``True``, a dummy forward pass is executed at construction
        time to trigger CUDA kernel JIT and weight materialisation so that
        the first real request does not pay cold-start latency.
