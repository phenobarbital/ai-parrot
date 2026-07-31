---
type: Wiki Entity
title: OpenAIEmbeddingModel
id: class:parrot.embeddings.openai.OpenAIEmbeddingModel
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A wrapper class for OpenAI Embedding models.
relates_to:
- concept: class:parrot.embeddings.base.EmbeddingModel
  rel: extends
---

# OpenAIEmbeddingModel

Defined in [`parrot.embeddings.openai`](../summaries/mod:parrot.embeddings.openai.md).

```python
class OpenAIEmbeddingModel(EmbeddingModel)
```

A wrapper class for OpenAI Embedding models.

## Methods

- `async def encode(self, texts: List[str], **kwargs) -> List[List[float]]` — Generate embeddings for a list of texts using AsyncOpenAI.
- `async def embed_query(self, text: str, as_nparray: bool=False) -> Union[List[float], List[np.ndarray]]` — Generates an embedding for a single query string asynchronously.
- `async def embed_documents(self, texts: List[str], batch_size: Optional[int]=None) -> List[List[float]]` — Generates embeddings for a list of documents asynchronously.
