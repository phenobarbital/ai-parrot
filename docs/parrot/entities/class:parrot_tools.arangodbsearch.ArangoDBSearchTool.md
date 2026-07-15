---
type: Wiki Entity
title: ArangoDBSearchTool
id: class:parrot_tools.arangodbsearch.ArangoDBSearchTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ArangoDB Vector Search Tool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ArangoDBSearchTool

Defined in [`parrot_tools.arangodbsearch`](../summaries/mod:parrot_tools.arangodbsearch.md).

```python
class ArangoDBSearchTool(AbstractTool)
```

ArangoDB Vector Search Tool.

Provides unified search capabilities across vector, full-text, and graph data.
Supports:
- Semantic vector search
- BM25 full-text search
- Hybrid search combining both approaches
- Graph-enhanced search with relationship context

## Methods

- `async def close(self)` — Close database connection.
