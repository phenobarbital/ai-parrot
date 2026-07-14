---
type: Wiki Entity
title: FormSubsection
id: class:parrot_formdesigner.core.schema.FormSubsection
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A visual sub-grouping of fields within a section.
---

# FormSubsection

Defined in [`parrot_formdesigner.core.schema`](../summaries/mod:parrot_formdesigner.core.schema.md).

```python
class FormSubsection(BaseModel)
```

A visual sub-grouping of fields within a section.

Subsections provide an additional level of organization below sections.
They co-exist alongside ``FormField`` items in ``FormSection.fields``,
giving renderers a grouping boundary (header, divider, container) without
creating a full section (which would affect wizard steps, accordion
panels, etc.).

Attributes:
    subsection_id: Unique identifier for this subsection within the form.
    title: Optional title displayed as a subsection header.
    description: Optional description shown under the subsection title.
    fields: List of fields in this subsection.
    depends_on: Dependency rule controlling conditional visibility.
    meta: Arbitrary metadata for renderer-specific extensions.
