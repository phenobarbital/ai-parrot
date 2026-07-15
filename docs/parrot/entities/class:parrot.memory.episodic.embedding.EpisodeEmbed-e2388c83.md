---
type: Wiki Entity
title: EpisodeEmbeddingProvider
id: class:parrot.memory.episodic.embedding.EpisodeEmbeddingProvider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Lazy-loading sentence-transformers embedding provider.
---

# EpisodeEmbeddingProvider

Defined in [`parrot.memory.episodic.embedding`](../summaries/mod:parrot.memory.episodic.embedding.md).

```python
class EpisodeEmbeddingProvider
```

Lazy-loading sentence-transformers embedding provider.

The model is loaded only on the first call to embed() or embed_batch(),
keeping import time minimal for applications that don't need embeddings
immediately.

Args:
    model_name: HuggingFace model identifier.
    dimension: Expected embedding dimension (validated on first load).
    device: Torch device string ("cpu", "cuda", etc.).
    batch_size: Maximum batch size for embed_batch().

## Methods

- `def dimension(self) -> int` — Return the embedding dimension.
- `async def embed(self, text: str) -> list[float]` — Embed a single text string.
- `async def embed_batch(self, texts: list[str]) -> list[list[float]]` — Embed multiple texts efficiently.
- `def get_searchable_text(episode: EpisodicMemory) -> str` — Build the text used for embedding an episode.
