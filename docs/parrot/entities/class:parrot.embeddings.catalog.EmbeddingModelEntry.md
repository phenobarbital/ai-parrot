---
type: Wiki Entity
title: EmbeddingModelEntry
id: class:parrot.embeddings.catalog.EmbeddingModelEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validation schema for a single catalog entry.
---

# EmbeddingModelEntry

Defined in [`parrot.embeddings.catalog`](../summaries/mod:parrot.embeddings.catalog.md).

```python
class EmbeddingModelEntry(BaseModel)
```

Validation schema for a single catalog entry.

Used at module import time to guarantee every entry in
EMBEDDING_MODELS is well-formed. The runtime exposed object remains
a plain dict for JSON-serialisation compatibility with the consumer API.

Attributes:
    model: HuggingFace model identifier or provider model ID.
    provider: One of ``"huggingface"``, ``"openai"``, ``"google"``.
    name: Human-readable display name.
    dimension: Embedding vector dimensionality (must be > 0).
    multilingual: Whether the model supports multiple languages.
    language: Primary language code (``"en"``, ``"multi"``, etc.).
    use_case: List of applicable use-case tags.
    description: Short prose description for operator UIs.
    metric_recommended: Similarity metric the model was trained with.
    requires_prefix: Whether query / passage prefixes are required.
    prefix_query: Prefix prepended to query text (if any).
    prefix_passage: Prefix prepended to passage text (if any).
    normalized_output: Whether the model outputs L2-normalised vectors.
    max_seq_length: Maximum input token length supported by the model.
    hnsw_compatible: Whether pgvector HNSW indexing is supported
        (dimension <= 2000).
    license: SPDX license identifier or ``"proprietary"``.
    recommended_score_threshold: Minimum similarity score below which
        retrieved chunks should be discarded by RAG consumers. Units
        match ``metric_recommended`` — for cosine/L2-normalised models
        the value sits in ``[0.0, 1.0]``; for raw dot product on
        non-normalised models (e.g. ``multi-qa-mpnet-base-dot-v1``)
        it can exceed 1.0. The global default of 0.7 is too aggressive
        for several models — for example ``multi-qa-mpnet-base-cos-v1``
        naturally produces scores in the 0.30-0.55 range.
    recommended_search_limit: Default top-k for vector retrieval that
        consumers should use when the operator has not configured one.
        Heavyweight instruct/long-context models warrant a smaller
        pool than fast lightweight encoders.
    matryoshka_dimensions: Optional list of supported Matryoshka dims.
