---
type: Wiki Entity
title: FormSection
id: class:parrot.forms.schema.FormSection
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A logical grouping of fields within a form.
---

# FormSection

Defined in [`parrot.forms.schema`](../summaries/mod:parrot.forms.schema.md).

```python
class FormSection(BaseModel)
```

A logical grouping of fields within a form.

Sections can be used to organize fields visually and in wizard-style forms
each section becomes a separate step.

The ``fields`` list may contain both ``FormField`` and ``FormSubsection``
items in any order.  Use :meth:`iter_fields` to iterate over all
``FormField`` instances (flattening through subsections).

Attributes:
    section_id: Unique identifier for this section.
    title: Optional title displayed as a section header.
    description: Optional description shown under the section title.
    fields: Ordered list of fields and subsections in this section.
    depends_on: Dependency rule controlling conditional section visibility.
    meta: Arbitrary metadata for renderer-specific extensions.

## Methods

- `def iter_fields(self) -> Iterator[FormField]` — Yield every ``FormField``, flattening through subsections.
