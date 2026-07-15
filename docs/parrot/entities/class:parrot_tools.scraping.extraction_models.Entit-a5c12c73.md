---
type: Wiki Entity
title: EntityFieldSpec
id: class:parrot_tools.scraping.extraction_models.EntityFieldSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Specification for a single field within an entity.
---

# EntityFieldSpec

Defined in [`parrot_tools.scraping.extraction_models`](../summaries/mod:parrot_tools.scraping.extraction_models.md).

```python
class EntityFieldSpec(BaseModel)
```

Specification for a single field within an entity.

Args:
    name: Snake_case name for this field (e.g. ``plan_name``).
    description: Human-readable description of what this field contains.
    field_type: Type of value expected — one of ``text``, ``number``,
        ``currency``, ``url``, ``boolean``, or ``list``.
    required: Whether this field must be present for the entity to be valid.
    selector: CSS or XPath selector to locate this field's element.
    selector_type: Whether ``selector`` is ``css`` or ``xpath``.
    extract_from: What to extract from the element: ``text``,
        ``attribute``, or ``html``.
    attribute: HTML attribute name to extract when ``extract_from`` is
        ``attribute``.
