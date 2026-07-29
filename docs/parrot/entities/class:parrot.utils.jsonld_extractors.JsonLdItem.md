---
type: Wiki Entity
title: JsonLdItem
id: class:parrot.utils.jsonld_extractors.JsonLdItem
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single structured item extracted from a JSON-LD block.
---

# JsonLdItem

Defined in [`parrot.utils.jsonld_extractors`](../summaries/mod:parrot.utils.jsonld_extractors.md).

```python
class JsonLdItem
```

A single structured item extracted from a JSON-LD block.

Attributes:
    content_kind: Semantic type label (e.g. ``"faq"``, ``"jsonld-product"``).
    source_type: Provenance label (e.g. ``"faq-jsonld"``, ``"product-jsonld"``).
    page_content: Plain-text representation optimised for embedding.
    row_data: Raw key/value data for downstream metadata.
    selector_name: Human-readable name used as the ``selector_name`` metadata
        field.  Defaults to ``content_kind`` when not explicitly set.
