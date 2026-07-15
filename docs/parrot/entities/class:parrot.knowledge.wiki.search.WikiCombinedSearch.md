---
type: Wiki Entity
title: WikiCombinedSearch
id: class:parrot.knowledge.wiki.search.WikiCombinedSearch
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified search across PageIndex and GraphIndex.
---

# WikiCombinedSearch

Defined in [`parrot.knowledge.wiki.search`](../summaries/mod:parrot.knowledge.wiki.search.md).

```python
class WikiCombinedSearch
```

Unified search across PageIndex and GraphIndex.

Attributes:
    _pi: ``PageIndexToolkit`` instance for tree-based search.
    _gi: ``GraphIndexToolkit`` instance for graph-based search.
    _weights: Score weights for each backend (must sum to ~1.0).
    logger: Standard Python logger.

Example::

    cs = WikiCombinedSearch(pi_toolkit, gi_toolkit)
    results = await cs.search("neural networks", mode="combined", top_k=10)

## Methods

- `async def search(self, query: str, mode: str='combined', top_k: int=10, tree_name: Optional[str]=None, weights: Optional[dict[str, float]]=None) -> list[WikiSearchResult]` — Search the wiki and return merged, ranked results.
- `async def find_related(self, page_id: str, depth: int=2) -> list[dict[str, Any]]` — Discover pages related to a given wiki page via graph traversal.
