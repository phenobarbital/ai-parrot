---
type: Wiki Entity
title: LateChunkingProcessor
id: class:parrot.stores.utils.chunking.LateChunkingProcessor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Late Chunking processor integrated with PgVectorStore.
---

# LateChunkingProcessor

Defined in [`parrot.stores.utils.chunking`](../summaries/mod:parrot.stores.utils.chunking.md).

```python
class LateChunkingProcessor
```

Late Chunking processor integrated with PgVectorStore.

Late chunking generates embeddings for the full document first, then creates
contextually-aware chunk embeddings that preserve the global document context.

## Methods

- `async def process_document_late_chunking(self, document_text: str, document_id: str, metadata: Optional[Dict[str, Any]]=None) -> Tuple[np.ndarray, List[ChunkInfo]]` — Process document with late chunking strategy.
- `async def process_document_three_level(self, document_text: str, document_id: str, metadata: Optional[Dict[str, Any]]=None, parent_chunk_size_tokens: int=4000, parent_chunk_overlap_tokens: int=200) -> Tuple[List[Document], List[ChunkInfo]]` — Split an oversized document into the 3-level hierarchy.
