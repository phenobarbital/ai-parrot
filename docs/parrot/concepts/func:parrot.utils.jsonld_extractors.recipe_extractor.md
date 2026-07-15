---
type: Concept
title: recipe_extractor()
id: func:parrot.utils.jsonld_extractors.recipe_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Recipe data from a JSON-LD node.
---

# recipe_extractor

```python
def recipe_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Recipe data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="Recipe"``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
