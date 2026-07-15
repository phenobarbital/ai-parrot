---
type: Concept
title: event_extractor()
id: func:parrot.utils.jsonld_extractors.event_extractor
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract Event data from a JSON-LD node.
---

# event_extractor

```python
def event_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Event data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="Event"``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
