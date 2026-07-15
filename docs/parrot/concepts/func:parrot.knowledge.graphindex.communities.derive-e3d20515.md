---
type: Concept
title: derive_community_label()
id: func:parrot.knowledge.graphindex.communities.derive_community_label
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Derive a deterministic, LLM-free label from member titles.
---

# derive_community_label

```python
def derive_community_label(titles: Iterable[str], max_terms: int=3) -> str
```

Derive a deterministic, LLM-free label from member titles.

Counts salient keyword frequency across the supplied titles and joins the
most common terms. Ties are broken alphabetically so the result is stable
across runs. Returns an empty string when no salient keyword survives
stopword filtering.

Args:
    titles: Member node titles to summarise.
    max_terms: Maximum number of keywords to include in the label.

Returns:
    A capitalised label such as ``"Payment Gateway"``, or ``""``.
