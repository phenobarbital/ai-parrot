---
type: Wiki Entity
title: WikiSearchResult
id: class:parrot.knowledge.wiki.models.WikiSearchResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified wiki search result.
---

# WikiSearchResult

Defined in [`parrot.knowledge.wiki.models`](../summaries/mod:parrot.knowledge.wiki.models.md).

```python
class WikiSearchResult(BaseModel)
```

Unified wiki search result.

Attributes:
    node_id: Stable page identifier (``concept_id`` on the WikiStore
        path; index node id on the legacy path).
    title: Human-readable page or node title.
    score: Normalised relevance score in [0, 1] after weight application.
    source: Which search leg produced this result — ``"lexical"`` /
        ``"vector"`` (WikiStore plane) or ``"pageindex"`` /
        ``"graphindex"`` (legacy toolkit path).
    snippet: Short excerpt or summary extracted from the page content.
    category: Optional WikiPageCategory if the page has one.
    token_count: Token cost of reading the full page body — used by
        context packing to budget progressive disclosure.
