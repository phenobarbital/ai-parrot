---
type: Wiki Entity
title: ImportDiffReport
id: class:parrot_formdesigner.tools.services.networkninja.ImportDiffReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aggregate report for a single networkninja form import.
---

# ImportDiffReport

Defined in [`parrot_formdesigner.tools.services.networkninja`](../summaries/mod:parrot_formdesigner.tools.services.networkninja.md).

```python
class ImportDiffReport(BaseModel)
```

Aggregate report for a single networkninja form import.

Attributes:
    form_id: The ``FormSchema.form_id`` produced by the import.
    source: Always ``"networkninja"``.
    imported_at: UTC timestamp of the import.
    fields: One entry per imported field column.
