---
type: Wiki Summary
title: parrot_formdesigner.tools.services.networkninja
id: mod:parrot_formdesigner.tools.services.networkninja
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: NetworkninjaFormService — NetworkNinja PostgreSQL form-source service.
relates_to:
- concept: class:parrot_formdesigner.tools.services.networkninja.ImportDiffEntry
  rel: defines
- concept: class:parrot_formdesigner.tools.services.networkninja.ImportDiffReport
  rel: defines
- concept: class:parrot_formdesigner.tools.services.networkninja.NetworkninjaFormService
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.tools.services.abstract
  rel: references
---

# `parrot_formdesigner.tools.services.networkninja`

NetworkninjaFormService — NetworkNinja PostgreSQL form-source service.

Migrated verbatim from DatabaseFormTool in tools/database_form.py.
Owns the SQL query, field-type map, and all mapping helpers.

## Classes

- **`ImportDiffEntry(BaseModel)`** — Per-field entry in an ImportDiffReport.
- **`ImportDiffReport(BaseModel)`** — Aggregate report for a single networkninja form import.
- **`NetworkninjaFormService(AbstractFormService)`** — NetworkNinja PostgreSQL form-source service.
