---
type: Wiki Entity
title: ExtractionResult
id: class:parrot_loaders.extractors.base.ExtractionResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of an extraction operation.
---

# ExtractionResult

Defined in [`parrot_loaders.extractors.base`](../summaries/mod:parrot_loaders.extractors.base.md).

```python
class ExtractionResult(BaseModel)
```

Result of an extraction operation.

Args:
    records: The extracted records.
    total: Total number of records extracted.
    errors: Error messages encountered during extraction.
    warnings: Warning messages (non-fatal issues).
    source_name: Human-readable name of the data source.
    extracted_at: Timestamp when extraction completed.
