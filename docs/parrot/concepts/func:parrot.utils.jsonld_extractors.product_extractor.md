---
type: Concept
title: product_extractor()
id: func:parrot.utils.jsonld_extractors.product_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Product data from a JSON-LD node.
---

# product_extractor

```python
def product_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Product data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="Product"`` or similar.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
