---
type: Wiki Entity
title: MetadataResolutionError
id: class:parrot_formdesigner.services.metadata_enricher.MetadataResolutionError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a required metadata field cannot be resolved.
---

# MetadataResolutionError

Defined in [`parrot_formdesigner.services.metadata_enricher`](../summaries/mod:parrot_formdesigner.services.metadata_enricher.md).

```python
class MetadataResolutionError(Exception)
```

Raised when a required metadata field cannot be resolved.

The handler maps this to HTTP 422 with the message in
``errors._metadata``.
