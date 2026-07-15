---
type: Concept
title: howto_extractor()
id: func:parrot.utils.jsonld_extractors.howto_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract HowTo data from a JSON-LD node.
---

# howto_extractor

```python
def howto_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract HowTo data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="HowTo"``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
