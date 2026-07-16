---
type: Wiki Entity
title: MultiStoreSearchTool
id: class:parrot_tools.multistoresearch.MultiStoreSearchTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-store search tool with BM25 reranking.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# MultiStoreSearchTool

Defined in [`parrot_tools.multistoresearch`](../summaries/mod:parrot_tools.multistoresearch.md).

```python
class MultiStoreSearchTool(AbstractTool)
```

Multi-store search tool with BM25 reranking.

Performs parallel searches across pgVector, FAISS, and ArangoDB,
then applies BM25S for intelligent reranking and priority selection.
