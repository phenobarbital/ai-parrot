---
type: Concept
title: place_extractor()
id: func:parrot.utils.jsonld_extractors.place_extractor
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract Place / LocalBusiness data from a JSON-LD node.
---

# place_extractor

```python
def place_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Place / LocalBusiness data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type`` in
        ``{"Place", "LocalBusiness", "Restaurant"}``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
