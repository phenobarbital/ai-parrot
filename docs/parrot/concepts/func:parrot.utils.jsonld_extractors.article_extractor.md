---
type: Concept
title: article_extractor()
id: func:parrot.utils.jsonld_extractors.article_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Article / NewsArticle / BlogPosting data from a JSON-LD node.
---

# article_extractor

```python
def article_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Article / NewsArticle / BlogPosting data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type`` in
        ``{"Article", "NewsArticle", "BlogPosting"}``.

Returns:
    List with one ``JsonLdItem`` (empty list if neither ``headline``
    nor ``name`` is present).
