---
type: Concept
title: person_extractor()
id: func:parrot.utils.jsonld_extractors.person_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Person data from a JSON-LD node.
---

# person_extractor

```python
def person_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Person data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="Person"``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
