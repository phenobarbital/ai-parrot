---
type: Wiki Entity
title: ImportDiffEntry
id: class:parrot_formdesigner.tools.services.networkninja.ImportDiffEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-field entry in an ImportDiffReport.
---

# ImportDiffEntry

Defined in [`parrot_formdesigner.tools.services.networkninja`](../summaries/mod:parrot_formdesigner.tools.services.networkninja.md).

```python
class ImportDiffEntry(BaseModel)
```

Per-field entry in an ImportDiffReport.

Attributes:
    column_name: The source ``column_name`` from ``form_metadata``.
    source_data_type: The raw ``data_type`` string from the source.
    mapped_field_type: The resolved ``FieldType.value`` string, or
        ``None`` when mapping failed.
    status: One of ``"mapeado"`` (fully mapped), ``"aproximado"``
        (approximate mapping with meta hint), or
        ``"requiere_intervencion"`` (manual review needed).
    note: Human-readable note about the mapping decision.
