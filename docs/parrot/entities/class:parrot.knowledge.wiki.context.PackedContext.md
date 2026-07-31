---
type: Wiki Entity
title: PackedContext
id: class:parrot.knowledge.wiki.context.PackedContext
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A budgeted, LLM-ready packing of wiki search results.
---

# PackedContext

Defined in [`parrot.knowledge.wiki.context`](../summaries/mod:parrot.knowledge.wiki.context.md).

```python
class PackedContext(BaseModel)
```

A budgeted, LLM-ready packing of wiki search results.

Attributes:
    text: Compact context block — one stub line per result.
    stubs: Structured stubs (id, title, lead, score, token cost of
        the FULL page — what ``wiki_read`` would spend).
    tokens_used: Estimated tokens of ``text``.
    results_packed: Number of results that fit the budget.
    total_available: Number of results before budgeting.
    truncated: ``True`` when the budget cut results off.
