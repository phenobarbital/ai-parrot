---
type: Wiki Entity
title: EmbeddingModel
id: class:parrot.embeddings.base.EmbeddingModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for embedding models.
---

# EmbeddingModel

Defined in [`parrot.embeddings.base`](../summaries/mod:parrot.embeddings.base.md).

```python
class EmbeddingModel(ABC)
```

Abstract base class for embedding models.
It ensures that embedding models can be used interchangeably.

## Methods

- `def device(self)`
- `def model(self)` — Return the raw library model (e.g. SentenceTransformer), never a wrapper.
- `def get_embedding_dimension(self) -> int`
- `async def initialize_model(self)` — Async model initialization with GPU optimization.
- `async def embed_documents(self, texts: List[str], batch_size: Optional[int]=None) -> List[List[float]]` — Generates embeddings for a list of documents.
- `async def embed_query(self, text: str, as_nparray: bool=False) -> Union[List[float], List[np.ndarray]]` — Generates an embedding for a single query string.
- `def free(self)` — Frees up resources used by the model.
- `async def encode(self, texts: List[str], **kwargs) -> np.ndarray`
