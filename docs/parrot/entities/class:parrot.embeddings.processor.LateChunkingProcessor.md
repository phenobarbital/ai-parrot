---
type: Wiki Entity
title: LateChunkingProcessor
id: class:parrot.embeddings.processor.LateChunkingProcessor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Processor for handling late chunking of documents using embeddings.
---

# LateChunkingProcessor

Defined in [`parrot.embeddings.processor`](../summaries/mod:parrot.embeddings.processor.md).

```python
class LateChunkingProcessor
```

Processor for handling late chunking of documents using embeddings.
This class processes documents by generating embeddings for the entire document first,
then splitting it into semantic chunks while preserving boundaries.
It uses the SentenceTransformerModel to generate embeddings and chunk metadata.

## Methods

- `async def process_document_late_chunking(self, document_text: str, document_id: str) -> Tuple[List[np.ndarray], List[Dict[str, Any]]]` — Process document with late chunking strategy
