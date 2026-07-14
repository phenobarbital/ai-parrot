---
type: Wiki Summary
title: parrot.outputs.a2ui.catalog.components.datatable
id: mod:parrot.outputs.a2ui.catalog.components.datatable
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI ``DataTable`` catalog component (Module 3).
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.components.datatable.DataTableComponent
  rel: defines
- concept: mod:parrot.outputs.a2ui.catalog
  rel: references
- concept: mod:parrot.outputs.a2ui.catalog.base
  rel: references
- concept: mod:parrot.outputs.a2ui.models
  rel: references
---

# `parrot.outputs.a2ui.catalog.components.datatable`

A2UI ``DataTable`` catalog component (Module 3).

Schema vocabulary is adapted from ``StructuredTableConfig``/``TableColumn``
(``parrot.models.outputs``): ``columns`` (name/type/title/format), ``totalRows``,
``truncated``. The INPUT-ONLY ``data`` array is replaced by a data-model binding.
The Pydantic class is not imported into the wire format.

## Classes

- **`DataTableComponent`** — The ``DataTable`` catalog component (display-only, ``requires_actions=False``).
