---
type: Concept
title: breadcrumb_extractor()
id: func:parrot.utils.jsonld_extractors.breadcrumb_extractor
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract BreadcrumbList data from a JSON-LD node.
---

# breadcrumb_extractor

```python
def breadcrumb_extractor(node: Dict[str, Any]) -> List[JsonLdItem]
```

Extract BreadcrumbList data from a JSON-LD node.

Emits ONE item with the full breadcrumb path as ``page_content``
(e.g. ``"Home > Products > Widget Pro"``).

Args:
    node: Parsed JSON-LD dict with ``@type="BreadcrumbList"``.

Returns:
    List with one ``JsonLdItem`` (empty list if no crumbs found).
