---
type: Wiki Entity
title: ExtractedEntity
id: class:parrot_tools.scraping.extraction_models.ExtractedEntity
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single structured entity extracted from a page.
---

# ExtractedEntity

Defined in [`parrot_tools.scraping.extraction_models`](../summaries/mod:parrot_tools.scraping.extraction_models.md).

```python
class ExtractedEntity(BaseModel)
```

A single structured entity extracted from a page.

Args:
    entity_type: Type label matching the EntitySpec that produced this
        entity.
    fields: Mapping of field name to extracted value.
    source_url: URL of the page this entity was extracted from.
    confidence: Confidence score (0.0–1.0) for this extraction.
    raw_text: Raw text content associated with this entity.
    rag_text: Natural language sentence for RAG indexing, populated by
        RecallProcessor.
