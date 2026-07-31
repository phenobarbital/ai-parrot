---
type: Wiki Entity
title: EntitySpec
id: class:parrot_tools.scraping.extraction_models.EntitySpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specification for one type of entity to extract.
---

# EntitySpec

Defined in [`parrot_tools.scraping.extraction_models`](../summaries/mod:parrot_tools.scraping.extraction_models.md).

```python
class EntitySpec(BaseModel)
```

Specification for one type of entity to extract.

Args:
    entity_type: Identifier for this entity type (e.g. ``product``, ``plan``).
    description: Human-readable description of what this entity represents.
    fields: List of field specs that make up this entity.
    repeating: Whether multiple instances of this entity appear on the page.
    container_selector: CSS/XPath selector wrapping one entity instance.
    container_selector_type: Whether ``container_selector`` is ``css`` or
        ``xpath``.
