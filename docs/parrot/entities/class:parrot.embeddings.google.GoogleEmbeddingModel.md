---
type: Wiki Entity
title: GoogleEmbeddingModel
id: class:parrot.embeddings.google.GoogleEmbeddingModel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A wrapper class for Google Embedding models using the Gemini API.
relates_to:
- concept: class:parrot.embeddings.base.EmbeddingModel
  rel: extends
---

# GoogleEmbeddingModel

Defined in [`parrot.embeddings.google`](../summaries/mod:parrot.embeddings.google.md).

```python
class GoogleEmbeddingModel(EmbeddingModel)
```

A wrapper class for Google Embedding models using the Gemini API.

## Methods

- `async def encode(self, texts: List[str], **kwargs) -> List[List[float]]`
- `async def embed_query(self, text: str, as_nparray: bool=False) -> Union[List[float], List[np.ndarray]]`
- `async def embed_documents(self, texts: List[str], batch_size: Optional[int]=None) -> List[List[float]]`
