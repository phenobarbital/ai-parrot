---
type: Wiki Entity
title: WikiPageCategory
id: class:parrot.knowledge.wiki.models.WikiPageCategory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Karpathy's wiki page type taxonomy.
---

# WikiPageCategory

Defined in [`parrot.knowledge.wiki.models`](../summaries/mod:parrot.knowledge.wiki.models.md).

```python
class WikiPageCategory(str, Enum)
```

Karpathy's wiki page type taxonomy.

Attributes:
    SUMMARY: High-level summary of a source document or topic.
    ENTITY: Named entity page (person, organisation, product, etc.).
    CONCEPT: Abstract concept or idea extracted from sources.
    COMPARISON: Side-by-side comparison of two or more topics.
    OVERVIEW: Broad overview spanning multiple related topics.
    SYNTHESIS: LLM-synthesised insight across several sources.
    ANSWER: Direct answer to a query, filed as a wiki page.
