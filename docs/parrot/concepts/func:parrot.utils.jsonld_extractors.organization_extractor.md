---
type: Concept
title: organization_extractor()
id: func:parrot.utils.jsonld_extractors.organization_extractor
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract Organization data from a JSON-LD node.
---

# organization_extractor

```python
def organization_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract Organization data from a JSON-LD node.

Args:
    node: Parsed JSON-LD dict with ``@type="Organization"``.

Returns:
    List with one ``JsonLdItem`` (empty list if ``name`` is absent).
