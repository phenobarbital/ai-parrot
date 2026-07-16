---
type: Wiki Entity
title: ExtractedRecord
id: class:parrot_loaders.extractors.base.ExtractedRecord
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single extracted record with its raw data and metadata.
---

# ExtractedRecord

Defined in [`parrot_loaders.extractors.base`](../summaries/mod:parrot_loaders.extractors.base.md).

```python
class ExtractedRecord(BaseModel)
```

A single extracted record with its raw data and metadata.

Args:
    data: Field values from the source (column→value mapping).
    metadata: Provenance info (source name, extraction timestamp, etc.).
