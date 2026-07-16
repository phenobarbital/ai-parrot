---
type: Concept
title: pack_results()
id: func:parrot.knowledge.wiki.context.pack_results
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pack search results into a token-budgeted context block.
---

# pack_results

```python
def pack_results(results: Iterable[Any], budget_tokens: int=DEFAULT_BUDGET_TOKENS) -> PackedContext
```

Pack search results into a token-budgeted context block.

Results are consumed in ranked order; packing stops as soon as the
next stub would exceed ``budget_tokens``.  Duplicate ids are
skipped.

Args:
    results: ``WikiSearchResult`` models or plain result dicts, in
        ranked order.
    budget_tokens: Hard token ceiling for the packed text.

Returns:
    A :class:`PackedContext`.
