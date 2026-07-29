---
type: Wiki Entity
title: SentenceTransformerModel
id: class:parrot.embeddings.huggingface.SentenceTransformerModel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A wrapper class for HuggingFace sentence-transformers embeddings.
relates_to:
- concept: class:parrot.embeddings.base.EmbeddingModel
  rel: extends
---

# SentenceTransformerModel

Defined in [`parrot.embeddings.huggingface`](../summaries/mod:parrot.embeddings.huggingface.md).

```python
class SentenceTransformerModel(EmbeddingModel)
```

A wrapper class for HuggingFace sentence-transformers embeddings.

Supports optional Matryoshka Representation Learning (MRL) truncation via
the ``matryoshka`` kwarg.  When enabled, ``embed_documents`` and
``embed_query`` slice the native-dim output to the requested dimension and
re-apply L2 normalisation so cosine similarity remains correct in the
lower-dimensional space.  ``get_embedding_dimension()`` then reports the
truncated dimension, so downstream consumers (pgvector table creation) see
the correct size.

The truncation is implemented with a plain numpy slice + renorm — we do NOT
rely on ``SentenceTransformer.encode(truncate_dim=N)`` because that
parameter is only available in newer sentence-transformers versions and the
project does not pin to those.

FEAT-237: Added ``backend`` and ``file_name`` kwargs for ONNX/OpenVINO
CPU-optimised inference via ``sentence-transformers>=5.0.0``.

## Methods

- `def model(self)` — Return the raw SentenceTransformer model, syncing dimension on load.
- `async def embed_documents(self, texts: List[str], batch_size: Optional[int]=None) -> List[List[float]]` — Encode documents, applying the family-specific passage prefix.
- `async def embed_query(self, text: str, as_nparray: bool=False) -> Any` — Encode a query, applying the family-specific query prefix.
- `async def encode(self, texts: List[str], **kwargs) -> np.ndarray`
